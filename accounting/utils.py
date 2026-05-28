from datetime import timedelta
from decimal import Decimal
from django.utils import timezone
from django.db import transaction
from django.db.models import F
from .models import GLAccount, JournalEntry, JournalLine, CashbookEntry, ARInvoice, LaybyPlan, LaybyItem


class MissingGLAccountError(Exception):
    """Required chart-of-accounts code is not present (run init_gl_accounts)."""


def get_account(code: str):
    return GLAccount.objects.get(code=code)


def require_gl(code: str) -> GLAccount:
    try:
        return GLAccount.objects.get(code=code)
    except GLAccount.DoesNotExist as e:
        raise MissingGLAccountError(
            f'GL account {code} is missing. Run: python manage.py init_gl_accounts'
        ) from e


# Tender type -> GL account code. Sales, expense payments, and refunds
# all settle through one of these asset accounts.
#
#   CASH          -> 1000 Cash on Hand
#   ECOCASH       -> 1010 EcoCash Float
#   BANK_TRANSFER -> 1020 Bank Current Account
#   CARD          -> 1020 (POS card machine settles to bank; split later if needed)
TENDER_TO_GL = {
    'CASH': '1000',
    'ECOCASH': '1010',
    'BANK_TRANSFER': '1020',
    'CARD': '1020',
}


def get_tender_account(tender_type: str) -> GLAccount:
    """Resolve a SalesTicket.tender_type (or equivalent) to its GL account."""
    code = TENDER_TO_GL.get((tender_type or 'CASH').upper(), '1000')
    return require_gl(code)


def get_expense_payment_credit_account(payment_method: str) -> GLAccount:
    """Credit side for expense JE. Maps tender-style codes onto the new GL layout
    and preserves the legacy CASH / non-CASH split for rows that still carry the
    old payment_method values."""
    pm = (payment_method or '').upper()
    if pm in TENDER_TO_GL:
        return get_tender_account(pm)
    if pm == 'CASH':
        return require_gl('1000')
    # Legacy non-CASH expense payments assumed to be bank settled.
    try:
        return require_gl('1020')
    except MissingGLAccountError:
        return require_gl('1000')

@transaction.atomic
def post_ticket(ticket, user=None):
    """Post a SalesTicket to GL, cashbook, ShopStock, and receivables.

    Idempotent via posted_to_gl / posted_to_cashbook / stock_posted flags
    and the one-to-one ARInvoice / LaybyPlan links on the ticket.

    Routes by terms:
      IMMEDIATE:  Dr tender acct, Cr Revenue (excl VAT), Cr Output VAT,
                  Dr COGS, Cr Inventory, drain ShopStock, write cashbook.
      CREDIT:     Dr AR,          Cr Revenue (excl VAT), Cr Output VAT,
                  Dr COGS, Cr Inventory, drain ShopStock, create ARInvoice.
                  No cashbook entry (cash not yet received).
      LAYBY:      Dr AR, Cr Unearned Revenue (full incl VAT), reserve stock
                  via ShopStock drain, create LaybyPlan + LaybyItems linked
                  to ticket. Revenue + VAT are recognised on fulfilment.
    """
    from inventory.models import SalesTicket, StockMovement, ShopStock

    if not isinstance(ticket, SalesTicket):
        raise TypeError('post_ticket expects a SalesTicket instance')

    if ticket.voided:
        return

    ticket.recalc_totals(save=False)
    total = Decimal(ticket.total_incl_vat or 0)
    if total <= 0:
        return

    if ticket.terms == SalesTicket.TERMS_IMMEDIATE:
        _post_ticket_immediate(ticket, user, total)
    elif ticket.terms == SalesTicket.TERMS_CREDIT:
        _post_ticket_credit(ticket, user, total)
    elif ticket.terms == SalesTicket.TERMS_LAYBY:
        _post_ticket_layby(ticket, user, total)
    else:
        raise ValueError(f'Unknown ticket.terms={ticket.terms!r}')

    if not ticket.stock_posted and ticket.terms in (
        SalesTicket.TERMS_IMMEDIATE,
        SalesTicket.TERMS_CREDIT,
        SalesTicket.TERMS_LAYBY,
    ):
        for line in ticket.lines.all():
            stock_row = ShopStock.get_or_create_for(
                ticket.shop, line.inventory_item, line.variant,
            )
            stock_row.quantity = max(0, stock_row.quantity - line.quantity)
            stock_row.save(update_fields=['quantity', 'last_updated'])

            # Keep legacy field in sync so the stock sheet stays accurate.
            if line.variant:
                line.variant.quantity_in_stock = max(0, line.variant.quantity_in_stock - line.quantity)
                line.variant.save(update_fields=['quantity_in_stock'])
            else:
                line.inventory_item.quantity_in_Stock = max(0, line.inventory_item.quantity_in_Stock - line.quantity)
                line.inventory_item.save(update_fields=['quantity_in_Stock'])

            StockMovement.objects.create(
                inventory_item=line.inventory_item,
                movement_type='OUT',
                quantity=line.quantity,
                reason=f'Sale {ticket.receipt_number} @ {ticket.shop.code}',
                shop=ticket.shop,
            )
        ticket.stock_posted = True
        ticket.save(update_fields=['stock_posted'])

    return ticket


def _ticket_cogs_lines(ticket, je):
    cogs_acct = require_gl('5000')
    inventory_acct = require_gl('1300')
    total_cogs = sum(
        (Decimal(line.unit_cost or 0) * line.quantity for line in ticket.lines.all()),
        Decimal('0'),
    )
    if total_cogs > 0:
        JournalLine.objects.create(entry=je, account=cogs_acct, debit=total_cogs, description='COGS')
        JournalLine.objects.create(entry=je, account=inventory_acct, credit=total_cogs, description='Inventory out')


def _post_ticket_immediate(ticket, user, total):
    revenue_excl = Decimal(ticket.subtotal_excl_vat or 0)
    vat_amount = Decimal(ticket.vat_total or 0)

    if not ticket.posted_to_gl:
        tender_acct = get_tender_account(ticket.tender_type)
        revenue = require_gl('4000')
        vat_payable = require_gl('2400') if vat_amount > 0 else None

        je = JournalEntry.objects.create(
            memo=f'Sales ticket {ticket.receipt_number} @ {ticket.shop.code}',
            reference=ticket.receipt_number,
            created_by=user or ticket.cashier,
            shop=ticket.shop,
        )
        JournalLine.objects.create(
            entry=je, account=tender_acct, debit=total,
            description=f'{ticket.get_tender_type_display()} received',
        )
        JournalLine.objects.create(
            entry=je, account=revenue, credit=revenue_excl,
            description='Sales revenue (excl VAT)',
        )
        if vat_payable and vat_amount > 0:
            JournalLine.objects.create(
                entry=je, account=vat_payable, credit=vat_amount,
                description='Output VAT',
            )
        _ticket_cogs_lines(ticket, je)
        je.assert_balanced()
        ticket.posted_to_gl = True
        ticket.save(update_fields=['posted_to_gl'])

    if not ticket.posted_to_cashbook:
        CashbookEntry.objects.create(
            date=timezone.localdate(),
            reference=ticket.receipt_number,
            description=f'Sale @ {ticket.shop.code} via {ticket.get_tender_type_display()}',
            category='SALES',
            receipt_amount=total,
            payment_amount=Decimal('0'),
            recorded_by=user or ticket.cashier,
            shop=ticket.shop,
        )
        ticket.posted_to_cashbook = True
        ticket.save(update_fields=['posted_to_cashbook'])


def _post_ticket_credit(ticket, user, total):
    if ticket.customer_id is None:
        raise ValueError('CREDIT ticket requires a customer')

    revenue_excl = Decimal(ticket.subtotal_excl_vat or 0)
    vat_amount = Decimal(ticket.vat_total or 0)

    # Credit-limit enforcement — mirrors the legacy make_sale() check.
    cust = ticket.customer
    limit = Decimal(cust.credit_limit or 0)
    current = Decimal(cust.current_balance or 0)
    if limit > 0 and (current + total) > limit:
        raise ValueError(
            f'Customer {cust.name} exceeds credit limit: balance ${current} + ticket ${total} > limit ${limit}'
        )

    if not ticket.posted_to_gl:
        ar_acct = require_gl('1200')
        revenue = require_gl('4000')
        vat_payable = require_gl('2400') if vat_amount > 0 else None

        ar_invoice = _get_or_create_ticket_ar_invoice(ticket)

        je = JournalEntry.objects.create(
            memo=f'Credit sale {ticket.receipt_number} @ {ticket.shop.code}',
            reference=ar_invoice.invoice_number,
            created_by=user or ticket.cashier,
            shop=ticket.shop,
        )
        JournalLine.objects.create(
            entry=je, account=ar_acct, debit=total,
            description=f'AR - {cust.name}', customer=cust,
        )
        JournalLine.objects.create(
            entry=je, account=revenue, credit=revenue_excl,
            description='Sales revenue (excl VAT)',
        )
        if vat_payable and vat_amount > 0:
            JournalLine.objects.create(
                entry=je, account=vat_payable, credit=vat_amount,
                description='Output VAT',
            )
        _ticket_cogs_lines(ticket, je)
        je.assert_balanced()

        cust.current_balance = current + total
        cust.save(update_fields=['current_balance'])

        ticket.posted_to_gl = True
        ticket.posted_to_cashbook = True  # No cashbook receipt until payment.
        ticket.save(update_fields=['posted_to_gl', 'posted_to_cashbook'])


def _get_or_create_ticket_ar_invoice(ticket):
    """Create (or return) the ARInvoice linked to this ticket."""
    existing = ARInvoice.objects.filter(ticket=ticket).first()
    if existing:
        return existing

    year = ticket.created_at.year
    prefix = f'AR-TKT-{year}-'
    existing = ARInvoice.objects.filter(invoice_number__startswith=prefix).values_list('invoice_number', flat=True)
    max_seq = 0
    for inv in existing:
        try:
            max_seq = max(max_seq, int(inv[len(prefix):]))
        except (ValueError, IndexError):
            continue
    invoice_number = f'{prefix}{max_seq + 1:04d}'

    ar_invoice = ARInvoice.objects.create(
        customer=ticket.customer,
        invoice_number=invoice_number,
        invoice_date=ticket.created_at.date(),
        due_date=ticket.created_at.date() + timedelta(days=30),
        total_amount=ticket.total_incl_vat,
        amount_paid=Decimal('0'),
        status='PENDING',
        ticket=ticket,
        shop=ticket.shop,
    )
    return ar_invoice


def _post_ticket_layby(ticket, user, total):
    if ticket.customer_id is None:
        raise ValueError('LAYBY ticket requires a customer')

    if not ticket.posted_to_gl:
        # create_layby_ar_invoice() posts the Dr AR / Cr Unearned journal and
        # the customer balance update. Revenue + VAT + COGS are recognised on
        # fulfilment (via post_layby_fulfillment), so the cashbook is written
        # per-LaybyPayment, not here.
        plan = _get_or_create_ticket_layby_plan(ticket)
        if not plan.ar_invoice:
            create_layby_ar_invoice(plan)

        ticket.posted_to_gl = True
        ticket.posted_to_cashbook = True
        ticket.save(update_fields=['posted_to_gl', 'posted_to_cashbook'])


def _get_or_create_ticket_layby_plan(ticket):
    """Create (or return) the LaybyPlan linked to this ticket, mirroring lines into LaybyItems."""
    existing = LaybyPlan.objects.filter(ticket=ticket).first()
    if existing:
        return existing

    plan = LaybyPlan.objects.create(
        customer=ticket.customer,
        deposit_amount=Decimal('0'),
        total_price=ticket.total_incl_vat,
        amount_paid=Decimal('0'),
        status='ACTIVE',
        shop=ticket.shop,
        ticket=ticket,
    )
    for line in ticket.lines.all():
        LaybyItem.objects.create(
            plan=plan,
            inventory_item=line.inventory_item,
            quantity=line.quantity,
            unit_price=line.unit_price_incl_vat,
        )
    return plan


@transaction.atomic
def post_inventory_receipt(import_order_item, user=None):
    """
    Post GL entry when inventory is received from an import order.
    Dr Inventory (1300), Cr Accounts Payable (2100) or Cash (1000)

    Args:
        import_order_item: ImportOrderItem instance that was received
        user: User who recorded the receipt (optional)
    """
    # Skip if already posted or no quantity received
    if not import_order_item.is_received or import_order_item.quantity_received <= 0:
        return

    # Calculate total landed cost for received quantity
    total_cost = import_order_item.landed_cost_per_unit * import_order_item.quantity_received

    if total_cost <= 0:
        return

    try:
        inventory_account = require_gl('1300')  # Inventory
        ap_account = require_gl('2000')  # Accounts Payable
    except MissingGLAccountError:
        return

    # Create journal entry
    import_order = import_order_item.import_order
    reference = f"{import_order.order_number}-{import_order_item.id}"

    je = JournalEntry.objects.create(
        memo=f"Inventory receipt from {import_order.supplier.name}",
        reference=reference,
        created_by=user
    )

    # Dr Inventory
    JournalLine.objects.create(
        entry=je,
        account=inventory_account,
        debit=total_cost,
        description=f"Received {import_order_item.quantity_received}x {import_order_item.inventory_item.name if import_order_item.inventory_item else import_order_item.product_name}",
        inventory_item=import_order_item.inventory_item
    )

    # Cr Accounts Payable
    JournalLine.objects.create(
        entry=je,
        account=ap_account,
        credit=total_cost,
        description=f"Payable to {import_order.supplier.name}"
    )

    je.assert_balanced()
    return je

@transaction.atomic
def post_supplier_payment(invoice_payment, user=None):
    """
    Post GL entry when paying a supplier invoice.
    Dr Accounts Payable (2000), Cr Cash (1000)

    Args:
        invoice_payment: InvoicePayment instance
        user: User who recorded the payment (optional)
    """
    amount = invoice_payment.amount
    if amount <= 0:
        return

    try:
        ap_account = require_gl('2000')  # Accounts Payable
        cash_account = require_gl('1000')  # Cash
    except MissingGLAccountError:
        return

    supplier = invoice_payment.invoice.import_order.supplier
    reference = invoice_payment.reference_number or invoice_payment.invoice.invoice_number

    je = JournalEntry.objects.create(
        memo=f"Supplier payment to {supplier.name}",
        reference=reference,
        created_by=user
    )

    # Dr Accounts Payable (reduce liability)
    JournalLine.objects.create(
        entry=je,
        account=ap_account,
        debit=amount,
        description=f"Payment to {supplier.name}"
    )

    # Cr Cash (reduce asset)
    JournalLine.objects.create(
        entry=je,
        account=cash_account,
        credit=amount,
        description=f"Supplier payment - {reference}"
    )

    je.assert_balanced()
    return je

@transaction.atomic
def post_sales_return(return_obj, user=None):
    """
    Post GL reversal entries for a sales return.
    Reverses: Revenue, COGS, Inventory, and Cash/AR

    Args:
        return_obj: Return model instance
        user: User who processed the return
    """
    sale = return_obj.sale
    quantity_returned = return_obj.quantity_returned

    if quantity_returned <= 0:
        return

    # Calculate amounts using net (post-discount) unit price to match original posting
    quantity_sold = sale.quantity_sold or 1
    net_unit_price = (sale.total_amount / quantity_sold) if quantity_sold else Decimal('0')
    unit_cost = sale.inventory_item.purchase_price or Decimal('0')

    revenue_reversal = net_unit_price * quantity_returned
    cogs_reversal = unit_cost * quantity_returned

    revenue = require_gl('4000')     # Sales Revenue
    cogs_acct = require_gl('5000')   # COGS
    inventory = require_gl('1300')   # Inventory

    # Determine if cash or credit sale
    if sale.payment_method == 'CASH':
        contra_account = require_gl('1000')  # Cash
        contra_desc = "Cash refund"
    else:  # CREDIT
        contra_account = require_gl('1200')  # AR
        contra_desc = "AR reduction"

    je = JournalEntry.objects.create(
        memo=f"Sales return - Sale #{sale.id}",
        reference=return_obj.return_number if hasattr(return_obj, 'return_number') else f"RET-{return_obj.id}",
        created_by=user
    )

    # Reverse Revenue: Dr Revenue, Cr Cash/AR
    JournalLine.objects.create(
        entry=je,
        account=revenue,
        debit=revenue_reversal,
        description='Revenue reversal - return',
        sale=sale
    )
    JournalLine.objects.create(
        entry=je,
        account=contra_account,
        credit=revenue_reversal,
        description=contra_desc,
        sale=sale,
        customer=sale.customer
    )

    # Reverse COGS: Dr Inventory, Cr COGS
    if cogs_reversal > 0:
        JournalLine.objects.create(
            entry=je,
            account=inventory,
            debit=cogs_reversal,
            description='Inventory restored - return',
            inventory_item=sale.inventory_item
        )
        JournalLine.objects.create(
            entry=je,
            account=cogs_acct,
            credit=cogs_reversal,
            description='COGS reversal - return',
            sale=sale
        )

    # Update customer balance if credit sale
    if sale.payment_method == 'CREDIT' and sale.customer:
        sale.customer.current_balance = (sale.customer.current_balance or Decimal('0')) - revenue_reversal
        sale.customer.save(update_fields=['current_balance'])

    je.assert_balanced()
    return je

@transaction.atomic
def post_inventory_adjustment(inventory_item, quantity, reason, adjustment_type='DAMAGE', user=None):
    """
    Post GL entry for inventory adjustments (damage, shrinkage, obsolescence).
    Dr Expense/Loss Account, Cr Inventory (1300)

    Args:
        inventory_item: Inventory instance
        quantity: Quantity being written off (positive number)
        reason: Description of why adjustment is made
        adjustment_type: 'DAMAGE', 'SHRINKAGE', 'OBSOLETE', 'ADJUSTMENT'
        user: User who recorded the adjustment
    """
    if quantity <= 0:
        return

    unit_cost = inventory_item.purchase_price or Decimal('0')
    total_cost = unit_cost * quantity

    if total_cost <= 0:
        return

    try:
        inventory_account = require_gl('1300')  # Inventory
        loss_account = require_gl('5000')  # COGS - could be a specific loss account
    except MissingGLAccountError:
        return

    je = JournalEntry.objects.create(
        memo=f"Inventory {adjustment_type.lower()} - {inventory_item.name}",
        reference=f"ADJ-{adjustment_type[:3]}-{inventory_item.id}",
        created_by=user
    )

    # Dr Loss/COGS (expense increases)
    JournalLine.objects.create(
        entry=je,
        account=loss_account,
        debit=total_cost,
        description=f"{adjustment_type}: {reason}",
        inventory_item=inventory_item
    )

    # Cr Inventory (asset decreases)
    JournalLine.objects.create(
        entry=je,
        account=inventory_account,
        credit=total_cost,
        description=f"Write-off: {quantity}x {inventory_item.name}",
        inventory_item=inventory_item
    )

    je.assert_balanced()
    return je

@transaction.atomic
def post_cash_sale(sale):
    """Post GL and cashbook for a cash sale. Idempotent via sale.posted flags.

    Uses gross method for discounts:
    - Dr Cash (net amount received)
    - Dr Sales Discounts (discount amount) - contra-revenue
    - Cr Sales Revenue (gross amount)
    """
    if sale.posted_to_gl and sale.posted_to_cashbook:
        return

    # Calculate gross and net amounts
    net_amount = Decimal(sale.total_amount or 0)
    if net_amount <= 0:
        return

    # Calculate gross amount (before discount)
    unit_price = Decimal(sale.sale_price or 0)
    quantity = Decimal(sale.quantity_sold or 0)
    gross_amount = unit_price * quantity

    # Calculate discount amount
    discount_percent = Decimal(sale.discount_applied or 0)
    discount_amount = gross_amount * (discount_percent / Decimal('100'))

    # COGS
    cogs = (sale.inventory_item.purchase_price or Decimal('0')) * (sale.quantity_sold or 0)

    discount_acct = None
    try:
        discount_acct = get_account('4100')  # Sales Discounts (contra-revenue)
    except GLAccount.DoesNotExist:
        pass

    if not sale.posted_to_gl:
        cash = require_gl('1000')
        revenue = require_gl('4000')
        cogs_acct = require_gl('5000')
        inventory = require_gl('1300')
        je = JournalEntry.objects.create(memo=f"Cash sale {sale.id}", reference=sale.receipt_number or str(sale.id), created_by=sale.recorded_by)

        JournalLine.objects.create(entry=je, account=cash, debit=net_amount, description='Cash received', sale_id=sale.id)

        if discount_amount > 0 and discount_acct:
            JournalLine.objects.create(entry=je, account=discount_acct, debit=discount_amount, description=f'Sales discount ({discount_percent}%)', sale_id=sale.id)
            JournalLine.objects.create(entry=je, account=revenue, credit=gross_amount, description='Sales revenue (gross)', sale_id=sale.id)
        else:
            JournalLine.objects.create(entry=je, account=revenue, credit=net_amount, description='Sales revenue', sale_id=sale.id)

        if cogs and cogs > 0:
            JournalLine.objects.create(entry=je, account=cogs_acct, debit=cogs, description='COGS', sale_id=sale.id, inventory_item_id=sale.inventory_item_id)
            JournalLine.objects.create(entry=je, account=inventory, credit=cogs, description='Inventory out', sale_id=sale.id, inventory_item_id=sale.inventory_item_id)
        je.assert_balanced()
        sale.posted_to_gl = True
        sale.save(update_fields=['posted_to_gl'])

    if not sale.posted_to_cashbook:
        CashbookEntry.objects.create(
            date=timezone.now().date(),
            reference=sale.receipt_number or f"SALE-{sale.id}",
            description=f"Cash sale - {sale.inventory_item.name}",
            category='SALES',
            receipt_amount=net_amount,
            payment_amount=0,
            recorded_by=sale.recorded_by,
        )
        sale.posted_to_cashbook = True
        sale.save(update_fields=['posted_to_cashbook'])

@transaction.atomic
def post_credit_sale(sale, customer_invoice: ARInvoice | None = None):
    """Post GL for a credit sale (Dr AR, Cr Revenue) + COGS/Inventory.
    If no ARInvoice passed, try to find one linked to the sale.

    Uses gross method for discounts:
    - Dr Accounts Receivable (net amount owed)
    - Dr Sales Discounts (discount amount) - contra-revenue
    - Cr Sales Revenue (gross amount)
    """
    if sale.posted_to_gl:
        return

    # Calculate gross and net amounts
    net_amount = Decimal(sale.total_amount or 0)
    if net_amount <= 0:
        return

    # Calculate gross amount (before discount)
    unit_price = Decimal(sale.sale_price or 0)
    quantity = Decimal(sale.quantity_sold or 0)
    gross_amount = unit_price * quantity

    # Calculate discount amount
    discount_percent = Decimal(sale.discount_applied or 0)
    discount_amount = gross_amount * (discount_percent / Decimal('100'))

    if customer_invoice is None:
        customer_invoice = ARInvoice.objects.filter(sale_id=sale.id).first()

    discount_acct = None
    try:
        discount_acct = get_account('4100')
    except GLAccount.DoesNotExist:
        pass

    ar = require_gl('1200')
    revenue = require_gl('4000')
    cogs_acct = require_gl('5000')
    inventory = require_gl('1300')

    je = JournalEntry.objects.create(memo=f"Credit sale {sale.id}", reference=(customer_invoice.invoice_number if customer_invoice else str(sale.id)), created_by=sale.recorded_by)

    # Dr Accounts Receivable (net amount customer owes)
    JournalLine.objects.create(entry=je, account=ar, debit=net_amount, description='Credit sale', sale_id=sale.id, customer_id=sale.customer_id)

    # Dr Sales Discounts (if discount was given and account exists)
    if discount_amount > 0 and discount_acct:
        JournalLine.objects.create(entry=je, account=discount_acct, debit=discount_amount, description=f'Sales discount ({discount_percent}%)', sale_id=sale.id)
        # Cr Revenue (gross amount)
        JournalLine.objects.create(entry=je, account=revenue, credit=gross_amount, description='Sales revenue (gross)', sale_id=sale.id)
    else:
        # No discount - post net amount as revenue
        JournalLine.objects.create(entry=je, account=revenue, credit=net_amount, description='Sales revenue', sale_id=sale.id)

    cogs = (sale.inventory_item.purchase_price or Decimal('0')) * (sale.quantity_sold or 0)
    if cogs and cogs > 0:
        JournalLine.objects.create(entry=je, account=cogs_acct, debit=cogs, description='COGS', sale_id=sale.id, inventory_item_id=sale.inventory_item_id)
        JournalLine.objects.create(entry=je, account=inventory, credit=cogs, description='Inventory out', sale_id=sale.id, inventory_item_id=sale.inventory_item_id)

    je.assert_balanced()
    sale.posted_to_gl = True
    sale.save(update_fields=['posted_to_gl'])

# Helper to create AR invoice for layby plan
@transaction.atomic
def create_layby_ar_invoice(plan):
    """Create AR invoice for a layby plan to track receivables properly."""
    # Don't create duplicate invoice
    if plan.ar_invoice:
        return plan.ar_invoice

    # Generate invoice number — scan all matching numbers to find true max
    # (lexicographic ORDER BY would mis-sort e.g. 0009 > 0010)
    year = plan.created_date.year
    prefix = f"AR-LAYBY-{year}-"
    existing = ARInvoice.objects.filter(
        invoice_number__startswith=prefix
    ).values_list('invoice_number', flat=True)

    max_num = 0
    for inv_num in existing:
        try:
            num = int(inv_num[len(prefix):])
            max_num = max(max_num, num)
        except (ValueError, IndexError):
            pass

    invoice_number = f"{prefix}{max_num + 1:04d}"

    # Create AR invoice
    ar_invoice = ARInvoice.objects.create(
        customer=plan.customer,
        invoice_number=invoice_number,
        invoice_date=plan.created_date.date() if hasattr(plan.created_date, 'date') else plan.created_date,
        due_date=plan.due_date or (plan.created_date.date() if hasattr(plan.created_date, 'date') else plan.created_date) + timedelta(days=30),
        total_amount=plan.total_price,
        amount_paid=plan.amount_paid,
        status='PENDING',
        shop=plan.shop,
    )

    # Link to plan
    plan.ar_invoice = ar_invoice
    plan.save(update_fields=['ar_invoice'])

    # Post initial AR journal entry: Dr AR, Cr Unearned Revenue
    ar = require_gl('1200')
    unearned = require_gl('2300')
    je = JournalEntry.objects.create(
        memo=f"Layby plan AR invoice {invoice_number}",
        reference=invoice_number,
        created_by=None,
        shop=plan.shop,
    )
    JournalLine.objects.create(
        entry=je,
        account=ar,
        debit=plan.total_price,
        description=f'Layby AR - Plan #{plan.id}',
        customer=plan.customer
    )
    JournalLine.objects.create(
        entry=je,
        account=unearned,
        credit=plan.total_price,
        description=f'Layby commitment - Plan #{plan.id}'
    )
    je.assert_balanced()

    plan.customer.current_balance = (plan.customer.current_balance or Decimal('0')) + plan.total_price
    plan.customer.save(update_fields=['current_balance'])

    return ar_invoice

# Helper to post layby fulfillment (recognize revenue from unearned)
@transaction.atomic
def post_layby_fulfillment(plan, amount, sale=None):
    revenue = require_gl('4000')
    unearned = require_gl('2300')
    cogs_acct = require_gl('5000')
    inventory = require_gl('1300')
    je = JournalEntry.objects.create(memo=f"Layby fulfillment plan#{plan.id}", created_by=None)
    JournalLine.objects.create(entry=je, account=unearned, debit=amount, description='Unearned -> Revenue')
    JournalLine.objects.create(entry=je, account=revenue, credit=amount, description='Recognized revenue')
    if sale:
        cogs_full = (sale.inventory_item.purchase_price or Decimal('0')) * (sale.quantity_sold or 0)
        total_price = plan.total_price or Decimal('0')
        if total_price > 0 and amount < total_price:
            cogs = (cogs_full * amount / total_price).quantize(Decimal('0.01'))
        else:
            cogs = cogs_full
        if cogs and cogs > 0:
            JournalLine.objects.create(entry=je, account=cogs_acct, debit=cogs, description='COGS', sale_id=sale.id)
            JournalLine.objects.create(entry=je, account=inventory, credit=cogs, description='Inventory out', sale_id=sale.id)
    je.assert_balanced()

@transaction.atomic
def post_return_from_ticket(return_obj, user=None):
    """Reverse GL for a ticket-based return + refund via chosen tender.

    The reversal is proportional to the quantity returned vs quantity sold on
    that line. Posts:
      Dr Sales Revenue (excl VAT)
      Dr Output VAT (if line was taxable)
      Cr Refund tender account (Cash / EcoCash / Bank / etc.)
      Dr Inventory (restock if is_restockable)
      Cr COGS (restock) OR stays written off via Inventory Loss
    """
    from inventory.models import ShopStock, StockMovement

    if return_obj.posted_to_gl:
        return

    line = return_obj.ticket_line
    if not line:
        return

    ticket = line.ticket
    qty_returned = Decimal(return_obj.quantity_returned)
    qty_sold = Decimal(line.quantity)
    if qty_sold <= 0 or qty_returned <= 0:
        return

    ratio = qty_returned / qty_sold
    return_total_incl = (line.line_total_incl_vat * ratio).quantize(Decimal('0.01'))
    return_vat = (line.vat_amount * ratio).quantize(Decimal('0.01'))
    return_excl = return_total_incl - return_vat
    return_cost = (Decimal(line.unit_cost) * qty_returned).quantize(Decimal('0.01'))

    if not return_obj.refund_amount or return_obj.refund_amount == Decimal('0'):
        return_obj.refund_amount = return_total_incl

    revenue = require_gl('4000')
    vat_payable = require_gl('2400') if return_vat > 0 else None
    cogs_acct = require_gl('5000')
    inventory_acct = require_gl('1300')
    inv_loss_acct = require_gl('5100')

    # Refund tender account
    refund_tender = return_obj.refund_tender
    if refund_tender in ('CASH', 'ECOCASH', 'BANK_TRANSFER', 'CARD'):
        tender_acct = get_tender_account(refund_tender)
    elif refund_tender == 'AR_CREDIT':
        # Reduce customer AR balance — use AR account
        tender_acct = require_gl('1200')
    else:
        # STORE_CREDIT — treat as customer liability for now, park in 2300 Unearned
        tender_acct = require_gl('2300')

    je = JournalEntry.objects.create(
        memo=f'Return vs {ticket.receipt_number} @ {ticket.shop.code}',
        reference=f'RTN-{ticket.receipt_number}-{return_obj.pk}',
        created_by=user,
        shop=ticket.shop,
    )

    # Dr Revenue (reverse)
    JournalLine.objects.create(
        entry=je, account=revenue, debit=return_excl,
        description=f'Return reversal — {line.inventory_item.name}',
    )
    # Dr Output VAT (reverse)
    if vat_payable and return_vat > 0:
        JournalLine.objects.create(
            entry=je, account=vat_payable, debit=return_vat,
            description='Output VAT reversal',
        )
    # Cr Tender (refund paid out)
    JournalLine.objects.create(
        entry=je, account=tender_acct, credit=return_total_incl,
        description=f'{return_obj.get_refund_tender_display()} refund',
    )

    # Stock: restock or write off
    if return_obj.is_restockable and return_obj.restock_to_shop_id:
        # Dr Inventory, Cr COGS
        if return_cost > 0:
            JournalLine.objects.create(
                entry=je, account=inventory_acct, debit=return_cost,
                description='Inventory restocked on return',
            )
            JournalLine.objects.create(
                entry=je, account=cogs_acct, credit=return_cost,
                description='COGS reversal',
            )
        stock_row = ShopStock.get_or_create_for(
            return_obj.restock_to_shop, line.inventory_item, line.variant,
        )
        stock_row.quantity += int(qty_returned)
        stock_row.save(update_fields=['quantity', 'last_updated'])
        StockMovement.objects.create(
            inventory_item=line.inventory_item,
            movement_type='IN',
            quantity=int(qty_returned),
            reason=f'Return restock {ticket.receipt_number}',
            shop=return_obj.restock_to_shop,
        )
    else:
        # Goods not restockable — move to Inventory Loss
        if return_cost > 0:
            JournalLine.objects.create(
                entry=je, account=inv_loss_acct, debit=return_cost,
                description='Unsellable return — loss',
            )
            JournalLine.objects.create(
                entry=je, account=cogs_acct, credit=return_cost,
                description='COGS reversal (written off)',
            )

    je.assert_balanced()

    # Customer balance adjustment for CREDIT / LAYBY refunds
    if refund_tender == 'AR_CREDIT' and ticket.customer_id:
        ticket.customer.current_balance = (
            (ticket.customer.current_balance or Decimal('0')) - return_total_incl
        )
        ticket.customer.save(update_fields=['current_balance'])

    return_obj.posted_to_gl = True
    return_obj.save(update_fields=['posted_to_gl', 'refund_amount'])


@transaction.atomic
def post_damaged_goods(damaged, user=None):
    """Post Dr Inventory Loss (5100) / Cr Inventory (1300) at weighted cost."""
    unit_cost = damaged.inventory_item.purchase_price or Decimal('0')
    if damaged.variant and damaged.variant.purchase_price:
        unit_cost = damaged.variant.purchase_price
    total_loss = unit_cost * damaged.quantity_damaged
    if total_loss <= 0:
        return

    inv_loss = require_gl('5100')
    inventory = require_gl('1300')

    je = JournalEntry.objects.create(
        memo=f'Damage @ {damaged.shop.code if damaged.shop else "HQ"} — {damaged.damage_description[:80]}',
        reference=f'DMG-{damaged.pk}',
        created_by=user,
        shop=damaged.shop,
    )
    JournalLine.objects.create(
        entry=je, account=inv_loss, debit=total_loss,
        description=f'{damaged.quantity_damaged}x {damaged.inventory_item.name}',
    )
    JournalLine.objects.create(
        entry=je, account=inventory, credit=total_loss,
        description='Inventory written off (damaged)',
    )
    je.assert_balanced()
