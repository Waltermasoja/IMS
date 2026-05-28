"""Cashbook sheet importer: map rows to Expense / Inventory-purchase JE / archive."""
from decimal import Decimal

from accounting.models import CashbookEntry, Expense, GLAccount, JournalEntry, JournalLine
from accounting.utils import require_gl
from inventory.importers.context import RunContext
from inventory.importers.excel_loader import load_cashbook
from inventory.importers.historical import archive_row

LOG_PREFIX = '[IMPORT-EB][CASHBOOK]'

# Special sentinel values for non-Expense routings.
INVENTORY_PURCHASE = '__INVENTORY__'

# Substring → (expense_category_code, gl_account_code).
# - None mapping → owner draws / personal — archive only, no GL.
# - INVENTORY_PURCHASE in slot 0 → cap as Inventory (Dr 1300, Cr Cash) — not opex.
# Order matters; first match wins. List longer / more-specific keys first.
CATEGORY_MAP: list[tuple[str, tuple[str, str] | None]] = [
    # ── stock / inventory purchases (capitalised, NOT expensed) ───────────────
    ('vegas moda',          (INVENTORY_PURCHASE, '1300')),
    ('turkey stock',        (INVENTORY_PURCHASE, '1300')),
    ('turkey payments',     (INVENTORY_PURCHASE, '1300')),
    ('china ticket',        (INVENTORY_PURCHASE, '1300')),  # buyer-trip airfare
    ('stock pur',           (INVENTORY_PURCHASE, '1300')),
    ('stock procurement',   (INVENTORY_PURCHASE, '1300')),
    ('stock distribution',  (INVENTORY_PURCHASE, '1300')),
    # NB: a bare 'stock' would match anything containing the word; place it last
    # so more-specific stock rules win first.
    ('ajar stock',          (INVENTORY_PURCHASE, '1300')),
    # ── operating expenses ────────────────────────────────────────────────────
    ('rent',                ('RENT',      '6000')),
    ('opc',                 ('RENT',      '6000')),  # 'rentals & opc' = operating costs
    ('salaries',            ('WAGES',     '6200')),
    ('salary',              ('WAGES',     '6200')),
    ('wage',                ('WAGES',     '6200')),
    ('freight',             ('FREIGHT',   '6300')),
    ('duty',                ('FREIGHT',   '6300')),
    ('clearing',            ('FREIGHT',   '6300')),
    ('biker',               ('OTHER',     '6900')),  # courier delivery
    ('transport',           ('OTHER',     '6900')),
    ('fuel',                ('OTHER',     '6900')),
    ('travel',              ('OTHER',     '6900')),
    ('accomodation',        ('OTHER',     '6900')),
    ('accommodation',       ('OTHER',     '6900')),
    ('food',                ('OTHER',     '6900')),  # buyer-trip subsistence
    ('packaging',           ('OTHER',     '6900')),
    ('cleaning',            ('OTHER',     '6900')),
    ('refreshment',         ('OTHER',     '6900')),
    ('electric',            ('UTILITIES', '6100')),
    ('water',               ('UTILITIES', '6100')),
    ('utility',             ('UTILITIES', '6100')),
    ('licence',             ('OTHER',     '6900')),
    ('license',             ('OTHER',     '6900')),
    ('marketing',           ('MARKETING', '6400')),
    ('advert',              ('MARKETING', '6400')),
    ('loan',                ('OTHER',     '2100')),  # liability — loan repayment
    # ── admin / bank / tax ────────────────────────────────────────────────────
    ('zimra',               ('OTHER',     '6900')),
    ('tax',                 ('OTHER',     '6900')),
    ('transfer charge',     ('OTHER',     '6900')),
    ('sending charge',      ('OTHER',     '6900')),
    ('bank charge',         ('OTHER',     '6900')),
    ('fsbs',                ('OTHER',     '6900')),
    # ── owner draws / non-business — archive only ─────────────────────────────
    ('personal',            None),
    ('drawings',            None),
    ('tithe',               None),
    ('round',               None),  # 'monthly round', '1k round' = owner contributions
    ('roundtable',          None),
    ('misc',                None),
]

# Sentinel returned by _match_category when no substring hits.
_NO_MATCH = object()


def _match_category(description: str) -> tuple[str, str] | None | object:
    """Return (category_code, gl_code), None (skip), or _NO_MATCH sentinel."""
    lower = description.lower()
    for substring, mapping in CATEGORY_MAP:
        if substring in lower:
            return mapping
    return _NO_MATCH


def _derive_payment_method(cash, card, ecocash, zig_usd) -> str:
    """Pick the dominant payment method from the tender columns."""
    if cash:
        return 'CASH'
    if card:
        return 'CARD'
    if ecocash:
        return 'MOBILE'
    if zig_usd:
        return 'CARD'   # ZIG debit/pos maps to CARD after conversion
    return 'CASH'


def _archive(r: dict, date, ctx: RunContext) -> None:
    archive_row(
        sheet_name='cashbook',
        row_index=r['row_index'],
        row_data=r,
        record_date=date,
        shop=ctx.shop,
        source_workbook=ctx.source_workbook,
        counter=ctx.historical_counter,
    )


def _post_inventory_purchase(amount: Decimal, description: str, payment_method: str,
                             row_date, ctx: RunContext) -> None:
    """Capitalise a stock-purchase row: Dr 1300 Inventory, Cr 1000 Cash.

    Stock-purchase rows in the cashbook are NOT operating expenses — they
    increase the Inventory asset and decrease Cash. We post the JE directly
    and write a CashbookEntry payment row so the cash-flow trail is intact.
    The actual ImportOrder + ImportOrderItem records are out of scope here;
    this is a cash-out summary entry only.
    """
    inv_acct = require_gl('1300')
    cash_acct = require_gl('1000')
    je = JournalEntry.objects.create(
        memo=f'Stock purchase — {description[:200]}',
        shop=ctx.shop,
    )
    JournalLine.objects.create(entry=je, account=inv_acct,
                               debit=amount,  description='Inventory purchase')
    JournalLine.objects.create(entry=je, account=cash_acct,
                               credit=amount, description='Cash out — stock')
    je.assert_balanced()
    CashbookEntry.objects.create(
        date=row_date,
        reference=f'STOCK-{row_date.isoformat()}',
        description=f'Stock purchase — {description[:200]}',
        receipt_amount=Decimal('0'),
        payment_amount=amount,
        category='STOCK',
        recorded_by=ctx.cashier_user,
        shop=ctx.shop,
    )


def run(ctx: RunContext) -> None:
    rows = load_cashbook(ctx.workbook_path)
    expenses_created = 0
    inventory_purchases = 0
    archived = 0
    unmappable = 0

    for r in rows:
        row_date = r['date']
        description = r['description']

        # Plan R7: pre-cutoff rows MUST NOT go through Expense (Expense.save()
        # auto-posts JEs). Archive as HistoricalRecord and move on.
        if row_date is None or row_date < ctx.cutoff:
            _archive(r, row_date, ctx)
            archived += 1
            continue

        mapping = _match_category(description)

        if mapping is _NO_MATCH:
            ctx.unmappable_expenses.append({
                'sheet':         'cashbook',
                'row':           r['row_index'],
                'date':          row_date,
                'category_text': description,
                'description':   description,
                'amount':        r['amount'],
                'reason':        'no category match',
            })
            _archive(r, row_date, ctx)
            unmappable += 1
            archived += 1
            continue

        if mapping is None:
            # Owner draws / personal — archive only; no GL posting.
            _archive(r, row_date, ctx)
            archived += 1
            continue

        expense_cat, gl_code = mapping

        payment_method = _derive_payment_method(
            r['cash'], r['card'], r['ecocash'], r['zig_usd']
        )

        # Use the explicit total column when present; otherwise sum tender columns.
        if r['amount'] is not None:
            usd_amount = r['amount']
        else:
            usd_amount = (
                (r['cash']    or Decimal('0'))
                + (r['card']    or Decimal('0'))
                + (r['ecocash'] or Decimal('0'))
                + (r['zig_usd'] or Decimal('0'))
            )

        # Expense.amount validator requires >= 0.01; skip zero rows silently.
        if usd_amount <= Decimal('0'):
            _archive(r, row_date, ctx)
            archived += 1
            continue

        # Quantize to 2dp — the loader returns 2dp already after the global
        # excel_loader fix, but cumulative additions above could re-introduce
        # extra precision; re-quantize defensively before any JE write.
        usd_amount = usd_amount.quantize(Decimal('0.01'))

        # ── Inventory-purchase route: Dr 1300, Cr 1000 (skip Expense entirely) ─
        if expense_cat == INVENTORY_PURCHASE:
            _post_inventory_purchase(usd_amount, description, payment_method,
                                     row_date, ctx)
            ctx.bump('inventory_purchases')
            inventory_purchases += 1
            continue

        gl_account = GLAccount.objects.get(code=gl_code)

        # Expense.save() auto-posts the JE and creates the CashbookEntry — do
        # NOT create CashbookEntry manually here.
        Expense.objects.create(
            date=row_date,
            category=expense_cat,
            description=description[:255],
            amount=usd_amount,
            vat_amount=Decimal('0'),
            gl_account=gl_account,
            payment_method=payment_method,
            shop=ctx.shop,
            recorded_by=ctx.cashier_user,
        )
        ctx.bump('expenses_created')
        expenses_created += 1

    ctx.log(
        f'{LOG_PREFIX} cashbook: {expenses_created} expenses, '
        f'{inventory_purchases} stock purchases, '
        f'{archived} archived, {unmappable} unmappable'
    )
