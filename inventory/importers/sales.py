"""
Daily-sales sheet → SalesTicket + SalesLine importer (Phase 5).

Pre-cutoff rows are archived to HistoricalRecord. Post-cutoff rows produce
live SalesTicket + SalesLine records and are posted to GL/cashbook/stock via
accounting.utils.post_ticket(). LAYBY/CREDIT instalment rows whose description
is a customer-name marker (e.g. "LAYBY INST MANYUMWA", "cr inst lydia") record
a payment against an existing plan/AR invoice and skip the fuzzy product match
entirely — the description is NOT a product reference for those rows.
"""
import re
from datetime import datetime, time
from decimal import Decimal

from django.utils import timezone

from accounting.models import (
    ARInvoice, ARPayment, CashbookEntry, JournalEntry, JournalLine,
    LaybyPlan, LaybyPayment,
)
from accounting.utils import post_ticket, require_gl
from inventory.importers import LOG_PREFIX
from inventory.importers import dry_run
from inventory.importers.context import RunContext
from inventory.importers.excel_loader import load_daily_sales
from inventory.importers.historical import archive_row
from inventory.models import Customer, Inventory, ProductVariant, SalesLine, SalesTicket

_SHEET = 'daily sales'

# Ordered prefixes used when parsing customer names from description strings.
# Longer / more-specific prefixes MUST come before shorter ones — first match
# wins and the rest of the string after the prefix is treated as the name.
_CUSTOMER_PREFIXES: tuple[str, ...] = (
    'LAYBY INST',
    'LAYBY CASH',
    'LAYBY CARD',
    'LAYBY',
    'CR INST',          # workbook uses "cr inst" for credit instalments
    'CR PUR',           # "cr pur" = credit purchase initiation
    'CREDIT INST',
    'CREDIT CASH',
    'CREDIT CARD',
    'CREDIT',
    'INST',
)

# A description starting with any of these is a *payment marker* — the text
# after the prefix is a customer name, not a product. We skip fuzzy match for
# those rows and record a LaybyPayment / ARPayment instead.
_PAYMENT_MARKER_PREFIXES = _CUSTOMER_PREFIXES

# Token pattern that separates meaningful name words from stray symbols.
_CLEAN_RE = re.compile(r'[^A-Za-z0-9 \-\']')

# Splits "customer name - product description" on the FIRST " - " (or "-" with
# adjacent whitespace). The workbook convention is rigid here: in CR PUR / CR
# INST / LAYBY rows the dash always separates the customer from the product.
_NAME_PRODUCT_SPLIT = re.compile(r'\s*-\s*')

# Phrases that mark non-customer header / subtotal rows that occasionally appear
# in the credit-clients sheet or as descriptions in the daily-sales sheet. Any
# row whose customer-name slot matches one of these is skipped (and archived to
# HistoricalRecord) rather than turned into a Customer.
_HEADER_KEYWORDS = (
    'TOTAL', 'RETURNED',
    'BAL B/D', 'BAL BD', 'BAL B-D',
    'OPENING BAL', 'OPENING BALANCE',
    'BAD DEBTS', 'CREDIT BALANCE',
)

_MONTH_YEAR_RE = re.compile(
    r'\b(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\b.*\b(19|20)\d{2}\b',
    re.IGNORECASE,
)


def _is_header_row(name: str | None) -> bool:
    """True iff the extracted customer name looks like a subtotal/header row.

    Catches: 'TOTAL', 'RETURNED', 'TOTAL BAD DEBTS', 'TOTAL CREDIT BALANCE',
    'jan 2025. opening balance', 'may 2025 bal bd', 'jan 2026. opening bal',
    'JAN 2026 BAL B/D', 'jan. 2025 bal b/d'.
    """
    if not name:
        return False
    upper = name.strip().upper()
    if not upper:
        return False
    if any(k in upper for k in _HEADER_KEYWORDS):
        return True
    # Stand-alone month+year is a balance-carry marker (e.g. 'JAN 2026').
    # Only flag if the entire name is essentially the month+year — don't catch
    # a real customer who happens to mention a month in a note.
    if _MONTH_YEAR_RE.search(upper) and len(upper) <= 30:
        return True
    return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_tender(
    row: dict, zig_rate: Decimal,
) -> tuple[str | None, str | None, Decimal | None]:
    """Map spreadsheet amount columns to (terms, tender_type, gross_usd).

    Returns (None, None, None) when no positive amount can be identified.
    Priority order:
      1. layby instalment / deposit  (col 8 / col 9)  → LAYBY_PAYMENT
      2. credit payment              (col 11 / col 12) → CREDIT_PAYMENT
      3. credit-sale initiation      (col 10)         → CREDIT (new sale)
      4. layby-sale initiation       (col 7)          → LAYBY_INIT
      5. cash / card immediate       (col 5 / col 6)  → IMMEDIATE
      6. ZIG POS                     (col 3)          → IMMEDIATE/CARD (converted)
    """
    def _pos(key: str) -> Decimal | None:
        v = row.get(key)
        return v if (v is not None and v > 0) else None

    if _pos('layby_cash'):
        return 'LAYBY_PAYMENT', 'CASH', row['layby_cash']
    if _pos('layby_card'):
        return 'LAYBY_PAYMENT', 'CARD', row['layby_card']
    if _pos('credit_cash'):
        return 'CREDIT_PAYMENT', 'CASH', row['credit_cash']
    if _pos('credit_card'):
        return 'CREDIT_PAYMENT', 'CARD', row['credit_card']

    if _pos('credit_initial'):
        # New credit sale: the goods are delivered now, AR receivable booked.
        return 'CREDIT', 'CASH', row['credit_initial']
    if _pos('layby_initial'):
        # New layby plan opened — active plans live in the dedicated layby
        # sheet so this row is informational; archive only.
        return 'LAYBY_INIT', 'CASH', row['layby_initial']

    usd_cash = _pos('usd_cash')
    tender_cash = _pos('tender_cash')
    if usd_cash or tender_cash:
        amt = max(usd_cash or Decimal('0'), tender_cash or Decimal('0'))
        return 'IMMEDIATE', 'CASH', amt

    usd_pos = _pos('usd_pos')
    tender_pos = _pos('tender_pos')
    if usd_pos or tender_pos:
        amt = max(usd_pos or Decimal('0'), tender_pos or Decimal('0'))
        return 'IMMEDIATE', 'CARD', amt

    zig_pos = _pos('zig_pos')
    if zig_pos:
        return 'IMMEDIATE', 'CARD', (zig_pos / zig_rate).quantize(Decimal('0.01'))

    return None, None, None


def _is_payment_marker(description: str) -> bool:
    """True iff description starts with a layby/credit prefix → not a product."""
    upper = description.upper().strip()
    return any(upper.startswith(p) for p in _PAYMENT_MARKER_PREFIXES)


def _extract_customer_name(description: str) -> tuple[str | None, str | None]:
    """Return (customer_name, product_text) parsed from a description.

    The workbook convention for credit / layby rows is:
        "{PREFIX} {customer name} - {product description}"
    Examples:
        "CR PUR abiba - hairband fascinator"         -> ('abiba',          'hairband fascinator')
        "cr pur lydia shoe shop -round fascinator"   -> ('lydia shoe shop','round fascinator')
        "LAYBY INST MANYUMWA"                        -> ('MANYUMWA',       None)
        "china red dress"                            -> (None,             None)   # no prefix
    """
    upper = description.upper().strip()
    for prefix in _CUSTOMER_PREFIXES:
        if upper.startswith(prefix):
            remainder = description[len(prefix):].strip()
            # Split on first " - " (or "-" with surrounding whitespace).
            parts = _NAME_PRODUCT_SPLIT.split(remainder, maxsplit=1)
            customer = _CLEAN_RE.sub('', parts[0]).strip() or None
            product = parts[1].strip() if len(parts) > 1 else None
            return customer, (product or None)
    return None, None


def _normalize_name(name: str) -> str:
    """Canonical form for dedup: collapse whitespace, lower-case."""
    return ' '.join(name.split()).lower()


def _get_or_create_customer(description: str) -> tuple[Customer | None, str | None]:
    """Resolve a Customer + product-portion from a description string.

    Returns (customer_or_None, product_text_or_None).
    - customer is None when the extracted name is a header/subtotal marker
      (the caller should archive the row rather than create a transaction).
    - When no name can be extracted at all, falls back to 'Walk-in (imported)'.
    """
    name, product_text = _extract_customer_name(description)
    if name and _is_header_row(name):
        return None, product_text
    name = name or 'Walk-in (imported)'

    # Case-insensitive dedup — store the source casing the first time we see
    # the customer; later occurrences re-use that record.
    canonical = _normalize_name(name)
    cust = next(
        (c for c in Customer.objects.filter(name__iexact=name)),
        None,
    ) or Customer.objects.filter(name__iexact=canonical).first()
    if cust is None:
        cust = Customer.objects.create(name=name)
    return cust, product_text


def _record_layby_payment(cust: Customer, amount: Decimal,
                          row_date, row_idx: int, ctx: RunContext) -> bool:
    """Add a LaybyPayment to the customer's active plan. Return True if posted."""
    plan = LaybyPlan.objects.filter(customer=cust, status='ACTIVE').first()
    if plan is None:
        return False
    LaybyPayment.objects.create(
        plan=plan,
        amount=amount,
        payment_date=row_date,
        reference=f'IMPORT R{row_idx}',
        recorded_by=ctx.cashier_user,
    )
    ctx.bump('layby_payments')
    return True


def _record_ar_payment(cust: Customer, amount: Decimal, tender_type: str,
                       row_date, row_idx: int, ctx: RunContext) -> bool:
    """Add an ARPayment to the customer's oldest unpaid invoice. Return True if posted."""
    invoice = (
        ARInvoice.objects
        .filter(customer=cust)
        .exclude(status='PAID')
        .exclude(status='CANCELLED')
        .order_by('invoice_date')
        .first()
    )
    if invoice is None:
        return False
    method = 'CASH' if tender_type == 'CASH' else 'CARD'
    ARPayment.objects.create(
        invoice=invoice,
        payment_date=row_date,
        amount=amount,
        method=method,
        reference=f'IMPORT R{row_idx}',
        recorded_by=ctx.cashier_user,
    )
    ctx.bump('ar_payments')
    return True


def _post_bad_debt_recovery(cust: Customer, amount: Decimal, tender_type: str,
                            row_date, row_idx: int, ctx: RunContext) -> None:
    """Record a 2026 payment from a customer whose 2018-2024 AR was written off.

    Per the user-confirmed treatment (memory note exoticblossom_data_import.md):
    these payments are recoveries — Dr Cash, Cr 4800 Other Income (NOT a
    reversal of the bad-debt write-off, NOT an AR payment). We also write a
    CashbookEntry receipt so the cash trail is preserved.

    `cust` may be a new Customer record — we ensure they exist so the
    operator can see them in the system. We don't update current_balance
    because there is no live AR receivable.
    """
    cash_acct = require_gl('1000')
    other_income = require_gl('4800')

    je = JournalEntry.objects.create(
        memo=f'Bad-debt recovery — {cust.name}',
        shop=ctx.shop,
    )
    JournalLine.objects.create(
        entry=je, account=cash_acct,    debit=amount,
        description=f'Recovery from {cust.name}',
    )
    JournalLine.objects.create(
        entry=je, account=other_income, credit=amount,
        description=f'Bad-debt recovery — {cust.name}',
        customer=cust,
    )
    je.assert_balanced()

    CashbookEntry.objects.create(
        date=row_date,
        reference=f'RECOV-R{row_idx}',
        description=f'Bad-debt recovery — {cust.name}',
        receipt_amount=amount,
        payment_amount=Decimal('0'),
        category='RECOVERY',
        recorded_by=ctx.cashier_user,
        shop=ctx.shop,
    )

    ctx.bad_debt_recoveries.append({
        'customer_id':   cust.id,
        'customer_name': cust.name,
        'date':          row_date,
        'amount':        amount,
        'tender':        tender_type,
        'je_id':         je.id,
        'row_index':     row_idx,
    })
    ctx.bump('bad_debt_recoveries')


# ---------------------------------------------------------------------------
# Phase entry point
# ---------------------------------------------------------------------------

def run(ctx: RunContext) -> None:
    """Process daily-sales sheet. See module docstring for full contract."""
    rows = load_daily_sales(ctx.workbook_path)

    for row in rows:
        row_date = row['date']
        row_idx = row['row_index']
        description = row['description']

        # ── 2a: pre-cutoff rows → archive only ──────────────────────────────
        if row_date is None or row_date < ctx.cutoff:
            archive_row(
                sheet_name=_SHEET,
                row_index=row_idx,
                row_data=row,
                record_date=row_date,
                shop=ctx.shop,
                source_workbook=ctx.source_workbook,
                counter=ctx.historical_counter,
            )
            continue

        # ── 2b: tender determination ─────────────────────────────────────────
        terms, tender_type, gross_usd = _resolve_tender(row, ctx.zig_rate)
        if gross_usd is None:
            # Cost-only / memo rows (col[7] layby cost without an instalment,
            # standalone "cr pur X" labels, etc.) — these have a description
            # but no payment. Archive for the operator to review.
            ctx.unmatched_sales.append({
                'sheet': _SHEET, 'row': row_idx, 'date': row_date,
                'description': description, 'amount': None, 'tender': None,
                'reason': 'no tender',
            })
            archive_row(
                sheet_name=_SHEET, row_index=row_idx, row_data=row,
                record_date=row_date, shop=ctx.shop,
                source_workbook=ctx.source_workbook,
                counter=ctx.historical_counter,
            )
            continue

        # ── 2b-bis: layby-initiation rows ─ archive (active plans live in the
        #            dedicated 'layby clients' sheet so this is informational).
        if terms == 'LAYBY_INIT':
            archive_row(
                sheet_name=_SHEET, row_index=row_idx, row_data=row,
                record_date=row_date, shop=ctx.shop,
                source_workbook=ctx.source_workbook,
                counter=ctx.historical_counter,
            )
            ctx.bump('layby_init_archived')
            continue

        # ── 2b-ter: payment-marker rows (LAYBY INST X / cr inst Y) ───────────
        # Description is a customer name, not a product. Skip fuzzy match and
        # apply the payment to the customer's open plan / AR invoice. If no
        # open record exists, treat as a bad-debt recovery (Dr Cash Cr 4800).
        if _is_payment_marker(description):
            cust, _ = _get_or_create_customer(description)
            if cust is None:
                # Header/subtotal row masquerading as a payment marker — archive.
                archive_row(
                    sheet_name=_SHEET, row_index=row_idx, row_data=row,
                    record_date=row_date, shop=ctx.shop,
                    source_workbook=ctx.source_workbook,
                    counter=ctx.historical_counter,
                )
                ctx.bump('header_rows_archived')
                continue
            posted = False
            if terms == 'LAYBY_PAYMENT':
                posted = _record_layby_payment(cust, gross_usd, row_date,
                                               row_idx, ctx)
            elif terms == 'CREDIT_PAYMENT':
                posted = _record_ar_payment(cust, gross_usd, tender_type,
                                            row_date, row_idx, ctx)
            if posted:
                continue
            # No matching plan / invoice — this is a payment from someone
            # whose AR or layby was closed/written-off before the cutoff.
            # Treat as a bad-debt recovery: Dr Cash, Cr 4800 Other Income.
            _post_bad_debt_recovery(
                cust, gross_usd, tender_type, row_date, row_idx, ctx,
            )
            continue

        # Non-marker LAYBY_PAYMENT / CREDIT_PAYMENT rows shouldn't normally
        # exist (the description should always be a customer marker), but if
        # they do, fall through to the product-sale branches below treating
        # them as immediate sales. Flag so the operator notices.
        if terms == 'LAYBY_PAYMENT':
            terms = 'IMMEDIATE'
            ctx.bump('layby_payment_no_marker_fallback')
        elif terms == 'CREDIT_PAYMENT':
            terms = 'CREDIT'
            ctx.bump('credit_payment_no_marker_fallback')

        # ── 2c: fuzzy product match (only for product-sale rows) ─────────────
        # For CR PUR rows the description is "{prefix} {customer} - {product}".
        # Stripping the customer-name noise before fuzzy match raises hit-rate
        # noticeably (the product portion alone is what we want to match).
        fuzzy_input = description
        if terms == 'CREDIT':
            _, product_text = _extract_customer_name(description)
            if product_text:
                fuzzy_input = product_text
        result = ctx.fuzzy_matcher.match(fuzzy_input, _SHEET, row_idx)
        if result is None:
            ctx.unmatched_sales.append({
                'sheet': _SHEET, 'row': row_idx, 'date': row_date,
                'description': description, 'amount': gross_usd,
                'tender': tender_type,
                'reason': 'fuzzy below threshold',
            })
            # Do NOT archive — fuzzy_match_decisions.csv records the decision.
            continue

        # ── 2d: look up Inventory + optional ProductVariant ──────────────────
        try:
            inv = Inventory.objects.get(id=result.inventory_id)
        except Inventory.DoesNotExist:
            ctx.unmatched_sales.append({
                'sheet': _SHEET, 'row': row_idx, 'date': row_date,
                'description': description, 'amount': gross_usd,
                'tender': tender_type,
                'reason': f'Inventory id={result.inventory_id} not found',
            })
            continue

        var: ProductVariant | None = None
        if result.variant_id:
            var = ProductVariant.objects.filter(id=result.variant_id).first()

        # ── 2e/2f: create the SalesTicket ────────────────────────────────────
        if terms == 'CREDIT':
            cust, _ = _get_or_create_customer(description)
            if cust is None:
                # Header row in a CR PUR context shouldn't happen, but if it
                # does, drop the row to archive instead of creating bogus AR.
                archive_row(
                    sheet_name=_SHEET, row_index=row_idx, row_data=row,
                    record_date=row_date, shop=ctx.shop,
                    source_workbook=ctx.source_workbook,
                    counter=ctx.historical_counter,
                )
                ctx.bump('header_rows_archived')
                continue
            ticket = SalesTicket.objects.create(
                shop=ctx.shop, cashier=ctx.cashier_user, customer=cust,
                terms=SalesTicket.TERMS_CREDIT, tender_type=tender_type,
            )
        else:  # IMMEDIATE (cash or card)
            ticket = SalesTicket.objects.create(
                shop=ctx.shop, cashier=ctx.cashier_user, customer=None,
                terms=SalesTicket.TERMS_IMMEDIATE, tender_type=tender_type,
            )

        # ── 2g: create SalesLine ─────────────────────────────────────────────
        # quantity is always 1 — each spreadsheet row is one item sold.
        # vat_rate_applied=0 satisfies the 'VAT off' requirement.
        discount = row.get('discount') or Decimal('0')
        line = SalesLine(
            ticket=ticket,
            inventory_item=inv,
            variant=var,
            quantity=1,
            unit_price_incl_vat=gross_usd,
            discount_amount=discount,
            is_vat_exempt=False,
            vat_rate_applied=Decimal('0'),
        )
        line.compute(vat_rate=Decimal('0'))
        line.save()

        # ── 2h: recalc ticket header totals ──────────────────────────────────
        ticket.recalc_totals(save=True)

        # ── 2i: backdate created_at (bypasses default=timezone.now) ──────────
        # SalesTicket.created_at uses default=timezone.now — plain constructor
        # assignment is silently ignored.  Use .update() to bypass (plan R1).
        # Wrap in make_aware so USE_TZ=True doesn't warn about naive datetimes.
        backdated = timezone.make_aware(
            datetime.combine(row_date, time(12, 0))
        ) if timezone.is_naive(datetime.combine(row_date, time(12, 0))) \
          else datetime.combine(row_date, time(12, 0))
        dry_run.update_dates(SalesTicket, ticket.pk, created_at=backdated)

        # ── 2j: post GL / cashbook / stock ───────────────────────────────────
        post_ticket(ticket, user=ctx.cashier_user)

        # ── 2k: drain qoh_meta ───────────────────────────────────────────────
        slot = ctx.qoh_get(inv.id, var.id if var else None)
        slot['sold'] += 1

        # ── 2l: bump run counts ──────────────────────────────────────────────
        ctx.bump('tickets_created')
        ctx.bump('lines_created')

    # ── 3: negative QoH scan ─────────────────────────────────────────────────
    # Cache lookups to avoid repeated DB hits on the same ids.
    _inv_cache: dict[int, Inventory] = {}
    _var_cache: dict[int, ProductVariant | None] = {}

    for (inv_id, var_id), slot in ctx.qoh_meta.items():
        Q = slot['Q']
        sold = slot['sold']
        ful = slot['fulfilled_layby']
        cr = slot['credit_lines']
        qoh_calc = Q - sold - ful - cr
        if qoh_calc >= 0:
            continue

        if inv_id not in _inv_cache:
            try:
                _inv_cache[inv_id] = Inventory.objects.get(id=inv_id)
            except Inventory.DoesNotExist:
                _inv_cache[inv_id] = None  # type: ignore[assignment]
        cached_inv = _inv_cache[inv_id]
        if cached_inv is None:
            continue

        if var_id not in _var_cache:
            _var_cache[var_id] = ProductVariant.objects.filter(id=var_id).first() if var_id else None
        cached_var = _var_cache[var_id]

        ctx.negative_qoh.append({
            'product_code': cached_inv.product_code,
            'name': cached_inv.name,
            'variant_size': cached_var.attribute_string if cached_var else '',
            'shop_code': ctx.shop.code,
            'Q': Q,
            'sold': sold,
            'fulfilled_layby': ful,
            'credit_lines': cr,
            'qoh_calc': qoh_calc,
        })

    # ── 4: log summary ────────────────────────────────────────────────────────
    ctx.log(
        f'{LOG_PREFIX}[SALES] sales: '
        f'{ctx.counts.get("tickets_created", 0)} tickets, '
        f'{ctx.counts.get("layby_payments", 0)} layby payments, '
        f'{len(ctx.unmatched_sales)} unmatched'
    )
