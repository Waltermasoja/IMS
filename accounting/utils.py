from decimal import Decimal
from django.utils import timezone
from django.db import transaction
from django.db.models import F
from .models import GLAccount, JournalEntry, JournalLine, CashbookEntry, ARInvoice

def get_account(code: str):
    return GLAccount.objects.get(code=code)

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
        inventory_account = get_account('1300')  # Inventory
        # Default to Accounts Payable - could be extended to support cash purchases
        ap_account = get_account('2000')  # Accounts Payable
    except GLAccount.DoesNotExist:
        # If chart missing, skip GL posting
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
        ap_account = get_account('2000')  # Accounts Payable
        cash_account = get_account('1000')  # Cash
    except GLAccount.DoesNotExist:
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

    # Calculate amounts
    unit_price = sale.sale_price or Decimal('0')
    unit_cost = sale.inventory_item.purchase_price or Decimal('0')

    revenue_reversal = unit_price * quantity_returned
    cogs_reversal = unit_cost * quantity_returned

    try:
        revenue = get_account('4000')     # Sales Revenue
        cogs_acct = get_account('5000')   # COGS
        inventory = get_account('1300')   # Inventory

        # Determine if cash or credit sale
        if sale.payment_method == 'CASH':
            contra_account = get_account('1000')  # Cash
            contra_desc = "Cash refund"
        else:  # CREDIT
            contra_account = get_account('1200')  # AR
            contra_desc = "AR reduction"
    except GLAccount.DoesNotExist:
        return

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
        inventory_account = get_account('1300')  # Inventory
        # Use COGS account for inventory write-offs (or create specific loss account)
        loss_account = get_account('5000')  # COGS - could be a specific loss account
    except GLAccount.DoesNotExist:
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

    try:
        cash = get_account('1000')        # Cash
        revenue = get_account('4000')     # Sales Revenue
        cogs_acct = get_account('5000')   # COGS
        inventory = get_account('1300')   # Inventory
        # Try to get discount account, but don't fail if it doesn't exist
        try:
            discount_acct = get_account('4100')  # Sales Discounts (contra-revenue)
        except GLAccount.DoesNotExist:
            discount_acct = None
    except GLAccount.DoesNotExist:
        # If chart missing, skip GL posting but still record cashbook
        cash = revenue = cogs_acct = inventory = None

    if cash and revenue and cogs_acct and inventory and not sale.posted_to_gl:
        je = JournalEntry.objects.create(memo=f"Cash sale {sale.id}", reference=sale.receipt_number or str(sale.id), created_by=sale.recorded_by)

        # Dr Cash (net amount received)
        JournalLine.objects.create(entry=je, account=cash, debit=net_amount, description='Cash received', sale_id=sale.id)

        # Dr Sales Discounts (if discount was given and account exists)
        if discount_amount > 0 and discount_acct:
            JournalLine.objects.create(entry=je, account=discount_acct, debit=discount_amount, description=f'Sales discount ({discount_percent}%)', sale_id=sale.id)
            # Cr Revenue (gross amount)
            JournalLine.objects.create(entry=je, account=revenue, credit=gross_amount, description='Sales revenue (gross)', sale_id=sale.id)
        else:
            # No discount - post net amount as revenue
            JournalLine.objects.create(entry=je, account=revenue, credit=net_amount, description='Sales revenue', sale_id=sale.id)

        # Dr COGS, Cr Inventory
        if cogs and cogs > 0:
            JournalLine.objects.create(entry=je, account=cogs_acct, debit=cogs, description='COGS', sale_id=sale.id, inventory_item_id=sale.inventory_item_id)
            JournalLine.objects.create(entry=je, account=inventory, credit=cogs, description='Inventory out', sale_id=sale.id, inventory_item_id=sale.inventory_item_id)
        sale.posted_to_gl = True
        sale.save(update_fields=['posted_to_gl'])

    # Cashbook receipt (always uses net amount - actual cash received)
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

    try:
        ar = get_account('1200')          # Accounts Receivable
        revenue = get_account('4000')     # Sales Revenue
        cogs_acct = get_account('5000')   # COGS
        inventory = get_account('1300')   # Inventory
        # Try to get discount account, but don't fail if it doesn't exist
        try:
            discount_acct = get_account('4100')  # Sales Discounts (contra-revenue)
        except GLAccount.DoesNotExist:
            discount_acct = None
    except GLAccount.DoesNotExist:
        return

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

    sale.posted_to_gl = True
    sale.save(update_fields=['posted_to_gl'])

# Helper to create AR invoice for layby plan
@transaction.atomic
def create_layby_ar_invoice(plan):
    """Create AR invoice for a layby plan to track receivables properly."""
    from datetime import timedelta

    # Don't create duplicate invoice
    if plan.ar_invoice:
        return plan.ar_invoice

    # Generate invoice number
    year = plan.created_date.year
    last_invoice = ARInvoice.objects.filter(
        invoice_date__year=year
    ).order_by('-invoice_number').first()

    if last_invoice and last_invoice.invoice_number.startswith('AR-'):
        try:
            last_num = int(last_invoice.invoice_number.split('-')[-1])
            new_num = last_num + 1
        except (ValueError, IndexError):
            new_num = 1
    else:
        new_num = 1

    invoice_number = f"AR-LAYBY-{year}-{new_num:04d}"

    # Create AR invoice
    ar_invoice = ARInvoice.objects.create(
        customer=plan.customer,
        invoice_number=invoice_number,
        invoice_date=plan.created_date.date() if hasattr(plan.created_date, 'date') else plan.created_date,
        due_date=plan.due_date or (plan.created_date.date() if hasattr(plan.created_date, 'date') else plan.created_date) + timedelta(days=30),
        total_amount=plan.total_price,
        amount_paid=plan.amount_paid,
        status='PENDING'
    )

    # Link to plan
    plan.ar_invoice = ar_invoice
    plan.save(update_fields=['ar_invoice'])

    # Post initial AR journal entry: Dr AR, Cr Unearned Revenue
    try:
        ar = get_account('1200')
        unearned = get_account('2300')
        je = JournalEntry.objects.create(
            memo=f"Layby plan AR invoice {invoice_number}",
            reference=invoice_number,
            created_by=None
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
    except GLAccount.DoesNotExist:
        pass

    # Update customer balance
    plan.customer.current_balance = (plan.customer.current_balance or Decimal('0')) + plan.total_price
    plan.customer.save(update_fields=['current_balance'])

    return ar_invoice

# Helper to post layby fulfillment (recognize revenue from unearned)
@transaction.atomic
def post_layby_fulfillment(plan, amount, sale=None):
    try:
        revenue = get_account('4000')
        unearned = get_account('2300')
        cogs_acct = get_account('5000')
        inventory = get_account('1300')
    except GLAccount.DoesNotExist:
        return
    je = JournalEntry.objects.create(memo=f"Layby fulfillment plan#{plan.id}", created_by=None)
    # Recognize revenue
    JournalLine.objects.create(entry=je, account=unearned, debit=amount, description='Unearned -> Revenue')
    JournalLine.objects.create(entry=je, account=revenue, credit=amount, description='Recognized revenue')
    # Optional COGS/Inventory if sale provided
    if sale:
        cogs = (sale.inventory_item.purchase_price or Decimal('0')) * (sale.quantity_sold or 0)
        if cogs and cogs > 0:
            JournalLine.objects.create(entry=je, account=cogs_acct, debit=cogs, description='COGS', sale_id=sale.id)
            JournalLine.objects.create(entry=je, account=inventory, credit=cogs, description='Inventory out', sale_id=sale.id)