"""Phase 6 importer: active layby plans from the 'layby clients' sheet."""
from datetime import timedelta
from decimal import Decimal

from accounting.models import LaybyItem, LaybyPlan
from inventory.importers import dry_run, excel_loader, historical
from inventory.importers.context import RunContext
from inventory.models import Customer, Inventory

LOG_PREFIX = '[IMPORT-EB]'
_PLACEHOLDER_CODE = 'LAYBY-PLACEHOLDER'


def _get_or_create_placeholder(shop) -> Inventory:
    """Return (creating if absent) the single generic Inventory row used for
    all imported layby items that lack individual line-item breakdowns."""
    placeholder, _ = Inventory.objects.get_or_create(
        product_code=_PLACEHOLDER_CODE,
        defaults={
            'name': 'Imported layby (no line breakdown)',
            'label': 'IMPORTED',
            'has_variants': False,
            'selling_price': Decimal('0'),
            'purchase_price': Decimal('0'),
            'quantity_in_Stock': 0,
            'on_sale': False,
        },
    )
    return placeholder


def _get_or_create_customer(name: str) -> tuple[Customer, bool]:
    """Case-insensitive get-or-create for Customer by name.

    Re-uses any Customer already created by ar.py so that a customer who
    appears in both sheets is not duplicated.
    """
    existing = Customer.objects.filter(name__iexact=name).first()
    if existing:
        return existing, False

    customer = Customer.objects.create(
        name=name,
        credit_limit=Decimal('0'),
        current_balance=Decimal('0'),
        status='ACTIVE',
    )
    return customer, True


def _is_header_row_layby(name: str | None) -> bool:
    """Local re-export of sales._is_header_row to keep layby imports light."""
    from inventory.importers.sales import _is_header_row
    return _is_header_row(name)


def run(ctx: RunContext) -> None:
    """Import active layby plans (balance > 0) from the 'layby clients' sheet."""
    entries = excel_loader.load_layby_clients(ctx.workbook_path)

    if not entries:
        ctx.log(f'{LOG_PREFIX} layby: no active layby rows found — skipping phase.')
        return

    placeholder = _get_or_create_placeholder(ctx.shop)

    plans_created = 0

    header_skipped = 0
    for entry in entries:
        customer_name: str = entry['customer_name']
        purchase_date = entry['purchase_date']
        invoice_total: Decimal | None = entry['invoice_total']
        deposit: Decimal | None = entry['deposit']
        layby_balance: Decimal = entry['layby_balance']

        # ── Skip header / subtotal rows (sheet has 'TOTAL' and 'RETURNED'
        # rows as in-sheet summaries — they must NOT become customers).
        if _is_header_row_layby(customer_name):
            header_skipped += 1
            continue

        # ------------------------------------------------------------------
        # a. Customer — reuse existing or create a minimal stub.
        # ------------------------------------------------------------------
        customer, _ = _get_or_create_customer(customer_name)

        # ------------------------------------------------------------------
        # b. Derived financial fields.
        # ------------------------------------------------------------------
        deposit_amount = deposit if deposit is not None else Decimal('0')
        total_price = invoice_total if invoice_total is not None else layby_balance

        # amount_paid = portion already received (deposit + any instalments).
        # We treat this as "paid into plan" without re-posting a JE — per the
        # user decision: historical deposits are not re-posted to the cashbook
        # (no deposit dates available). The NEXT LaybyPayment from this
        # customer will flow through the normal model.save() chain.
        if invoice_total is not None:
            amount_paid = invoice_total - layby_balance
        else:
            amount_paid = Decimal('0')

        due_date = (purchase_date + timedelta(days=90)) if purchase_date else None

        # ------------------------------------------------------------------
        # b. Create LaybyPlan.
        # ------------------------------------------------------------------
        plan = LaybyPlan.objects.create(
            customer=customer,
            shop=ctx.shop,
            status='ACTIVE',
            deposit_amount=deposit_amount,
            total_price=total_price,
            amount_paid=amount_paid,
            due_date=due_date,
        )

        # Bypass auto_now_add to back-date created_date to purchase_date (plan R1).
        if purchase_date is not None:
            dry_run.update_dates(LaybyPlan, plan.pk, created_date=purchase_date)

        # ------------------------------------------------------------------
        # c. One placeholder LaybyItem — no individual line breakdown available.
        # ------------------------------------------------------------------
        LaybyItem.objects.create(
            plan=plan,
            inventory_item=placeholder,
            quantity=1,
            unit_price=total_price,
        )

        # ------------------------------------------------------------------
        # d. No JE posted here — see CONTRACT note (d) in module docstring.
        # ------------------------------------------------------------------

        # ------------------------------------------------------------------
        # e. Archive the source row to HistoricalRecord.
        # ------------------------------------------------------------------
        historical.archive_row(
            sheet_name='layby clients',
            row_index=entry['row_index'],
            row_data=entry,
            record_date=purchase_date,
            shop=ctx.shop,
            source_workbook=ctx.source_workbook,
            counter=ctx.historical_counter,
        )

        ctx.counts['layby_plans_active'] = ctx.counts.get('layby_plans_active', 0) + 1
        plans_created += 1

    ctx.log(
        f'{LOG_PREFIX} layby: created {plans_created} active plans, '
        f'{header_skipped} header rows skipped'
    )
