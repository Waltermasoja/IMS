from decimal import Decimal
from django.utils import timezone
from django.db import transaction
from django.db.models import F
from .models import GLAccount, JournalEntry, JournalLine, CashbookEntry, ARInvoice

def get_account(code: str):
    return GLAccount.objects.get(code=code)

@transaction.atomic
def post_cash_sale(sale):
    """Post GL and cashbook for a cash sale. Idempotent via sale.posted flags."""
    if sale.posted_to_gl and sale.posted_to_cashbook:
        return

    # Revenue
    amount = Decimal(sale.total_amount or 0)
    if amount <= 0:
        return

    # COGS
    cogs = (sale.inventory_item.purchase_price or Decimal('0')) * (sale.quantity_sold or 0)

    try:
        cash = get_account('1000')        # Cash
        revenue = get_account('4000')     # Sales Revenue
        cogs_acct = get_account('5000')   # COGS
        inventory = get_account('1300')   # Inventory
    except GLAccount.DoesNotExist:
        # If chart missing, skip GL posting but still record cashbook
        cash = revenue = cogs_acct = inventory = None

    if cash and revenue and cogs_acct and inventory and not sale.posted_to_gl:
        je = JournalEntry.objects.create(memo=f"Cash sale {sale.id}", reference=sale.receipt_number or str(sale.id), created_by=sale.recorded_by)
        # Dr Cash, Cr Revenue
        JournalLine.objects.create(entry=je, account=cash, debit=amount, description='Cash sale', sale_id=sale.id)
        JournalLine.objects.create(entry=je, account=revenue, credit=amount, description='Sales revenue', sale_id=sale.id)
        # Dr COGS, Cr Inventory
        if cogs and cogs > 0:
            JournalLine.objects.create(entry=je, account=cogs_acct, debit=cogs, description='COGS', sale_id=sale.id, inventory_item_id=sale.inventory_item_id)
            JournalLine.objects.create(entry=je, account=inventory, credit=cogs, description='Inventory out', sale_id=sale.id, inventory_item_id=sale.inventory_item_id)
        sale.posted_to_gl = True
        sale.save(update_fields=['posted_to_gl'])

    # Cashbook receipt
    if not sale.posted_to_cashbook:
        CashbookEntry.objects.create(
            date=timezone.now().date(),
            reference=sale.receipt_number or f"SALE-{sale.id}",
            description=f"Cash sale - {sale.inventory_item.name}",
            category='SALES',
            receipt_amount=amount,
            payment_amount=0,
            recorded_by=sale.recorded_by,
        )
        sale.posted_to_cashbook = True
        sale.save(update_fields=['posted_to_cashbook'])

@transaction.atomic
def post_credit_sale(sale, customer_invoice: ARInvoice | None = None):
    """Post GL for a credit sale (Dr AR, Cr Revenue) + COGS/Inventory.
    If no ARInvoice passed, try to find one linked to the sale.
    """
    if sale.posted_to_gl:
        return

    amount = Decimal(sale.total_amount or 0)
    if amount <= 0:
        return

    if customer_invoice is None:
        customer_invoice = ARInvoice.objects.filter(sale_id=sale.id).first()

    try:
        ar = get_account('1200')          # Accounts Receivable
        revenue = get_account('4000')     # Sales Revenue
        cogs_acct = get_account('5000')   # COGS
        inventory = get_account('1300')   # Inventory
    except GLAccount.DoesNotExist:
        return

    je = JournalEntry.objects.create(memo=f"Credit sale {sale.id}", reference=(customer_invoice.invoice_number if customer_invoice else str(sale.id)), created_by=sale.recorded_by)
    JournalLine.objects.create(entry=je, account=ar, debit=amount, description='Credit sale', sale_id=sale.id, customer_id=sale.customer_id)
    JournalLine.objects.create(entry=je, account=revenue, credit=amount, description='Sales revenue', sale_id=sale.id)

    cogs = (sale.inventory_item.purchase_price or Decimal('0')) * (sale.quantity_sold or 0)
    if cogs and cogs > 0:
        JournalLine.objects.create(entry=je, account=cogs_acct, debit=cogs, description='COGS', sale_id=sale.id, inventory_item_id=sale.inventory_item_id)
        JournalLine.objects.create(entry=je, account=inventory, credit=cogs, description='Inventory out', sale_id=sale.id, inventory_item_id=sale.inventory_item_id)

    sale.posted_to_gl = True
    sale.save(update_fields=['posted_to_gl'])

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