"""
Reconciliation CSV writer for the ExoticBlossom importer.

All audit outputs are written to `media/imports/{timestamp}/`. File I/O is
*intentionally outside* the transaction so dry-run rollbacks still produce a
review pack the operator can read.

The 11 CSVs match the audit-pack list in the plan
(`/home/kudzai/.claude/plans/lets-properly-go-through-zazzy-tide.md`).
"""
import csv
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Iterable

from django.conf import settings
from django.db.models import Sum

from accounting.models import ARInvoice, GLAccount, JournalLine
from inventory.models import Customer, ShopStock


def make_run_dir(timestamp: datetime | None = None) -> Path:
    """Create and return media/imports/{ts}/ for this importer run."""
    ts = (timestamp or datetime.utcnow()).strftime('%Y%m%dT%H%M%SZ')
    media_root = Path(settings.MEDIA_ROOT or 'media')
    out = media_root / 'imports' / ts
    out.mkdir(parents=True, exist_ok=True)
    return out


def _write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict]) -> int:
    count = 0
    with path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
            count += 1
    return count


# ---------------------------------------------------------------------------
# Data-derived CSVs (collected during the run, written at the end)
# ---------------------------------------------------------------------------

def write_fuzzy_decisions(out: Path, decisions: list[dict]) -> int:
    return _write_csv(
        out / 'fuzzy_match_decisions.csv',
        ['sheet', 'row', 'raw_description', 'matched_product_id',
         'matched_variant_id', 'matched_text', 'score', 'decision'],
        decisions,
    )


def write_unmatched_sales(out: Path, rows: list[dict]) -> int:
    return _write_csv(
        out / 'unmatched_sale_lines.csv',
        ['sheet', 'row', 'date', 'description', 'amount', 'tender', 'reason'],
        rows,
    )


def write_negative_qoh(out: Path, rows: list[dict]) -> int:
    return _write_csv(
        out / 'negative_qoh.csv',
        ['product_code', 'name', 'variant_size', 'shop_code',
         'opening_qty_imported', 'sold', 'fulfilled_layby',
         'credit_lines', 'qoh_calc'],
        rows,
    )


def write_stock_opening_audit(out: Path, rows: list[dict]) -> int:
    """Per-(product, variant) opening-stock tier + evidence (Plan A audit)."""
    return _write_csv(
        out / 'stock_opening_audit.csv',
        ['product_code', 'label', 'description', 'size',
         'tier', 'confidence', 'opening_qty_imported',
         'pur_price', 'total_pur_price', 'lot_units_raw',
         'rows_in_lot', 'rows_for_this_size', 'lot_rejected_reason'],
        rows,
    )


def write_pricing_sanity(out: Path, rows: list[dict]) -> int:
    """Pricing oddities (LOSS / DEEP_DISCOUNT / MISSING_SELL) — audit only."""
    return _write_csv(
        out / 'pricing_sanity.csv',
        ['flag', 'sheet', 'row', 'label', 'description',
         'pur_price', 'selling_price', 'sale_realized', 'detail'],
        rows,
    )


def write_column_drift(out: Path, rows: list[dict]) -> int:
    """Rows whose cell types don't match the expected column schema."""
    return _write_csv(
        out / 'column_drift.csv',
        ['sheet', 'row', 'column_index', 'column_name',
         'expected_type', 'actual_value', 'actual_type'],
        rows,
    )


def write_unmappable_expenses(out: Path, rows: list[dict]) -> int:
    return _write_csv(
        out / 'unmappable_expenses.csv',
        ['sheet', 'row', 'date', 'category_text', 'description', 'amount', 'reason'],
        rows,
    )


def write_bad_debt_writeoffs(out: Path, rows: list[dict]) -> int:
    return _write_csv(
        out / 'bad_debt_writeoffs.csv',
        ['customer_id', 'customer_name', 'original_invoice_date',
         'original_amount', 'writeoff_je_id'],
        rows,
    )


def write_bad_debt_recoveries(out: Path, rows: list[dict]) -> int:
    """2026+ payments received from customers whose AR was previously written off.

    Each row was posted as Dr 1000 Cash / Cr 4800 Other Income.
    """
    return _write_csv(
        out / 'bad_debt_recoveries.csv',
        ['customer_id', 'customer_name', 'date', 'amount', 'tender',
         'je_id', 'row_index'],
        rows,
    )


def write_opening_ar_journal(out: Path, rows: list[dict]) -> int:
    return _write_csv(
        out / 'opening_ar_journal.csv',
        ['customer_id', 'customer_name', 'je_id', 'je_date', 'total_amount',
         'ar_account', 'retained_earnings_account'],
        rows,
    )


def write_historical_archive_summary(out: Path, counter: dict) -> int:
    rows = [{'sheet': k, 'archived_rows': v} for k, v in sorted(counter.items())]
    return _write_csv(out / 'historical_archive_summary.csv', ['sheet', 'archived_rows'], rows)


def write_summary_text(out: Path, summary: dict) -> None:
    """Plain-text top-level summary for the operator (`import_summary.txt`)."""
    lines = [
        f'ExoticBlossom Import Summary',
        f'Generated: {datetime.utcnow().isoformat()}Z',
        f'Workbook:  {summary.get("workbook", "?")}',
        f'Shop:      {summary.get("shop_code", "?")}',
        f'Cutoff:    {summary.get("cutoff", "?")}',
        f'AR cutoff: {summary.get("ar_cutoff", "?")}',
        f'Mode:      {"COMMIT" if summary.get("commit") else "DRY-RUN"}',
        '',
        'Counts:',
    ]
    for k, v in summary.get('counts', {}).items():
        lines.append(f'  {k:30s} {v}')
    lines.append('')

    # Stock confidence block — Plan A polish.
    sc = summary.get('stock_confidence') or {}
    if sc:
        lines.append('=== ShopStock confidence ===')
        lines.append('ShopStock confidence: LOW')
        lines.append('  Reason: workbook has no units-sold signal to validate against.')
        lines.append('  Numbers are best-effort estimates from tiered signals (see')
        lines.append('  stock_opening_audit.csv). REQUIRED before go-live: a physical')
        lines.append('  stocktake via the Plan B `apply_stocktake` workflow.')
        lines.append('')
        lines.append(f'  Total (product, variant) rows estimated: {sc.get("total_variants_estimated", 0)}')
        lines.append('')
        lines.append('  Tier histogram (which signal was used per row):')
        for tier, n in sorted(sc.get('tiers', {}).items()):
            lines.append(f'    {tier:20s} {n}')
        lines.append('')
        lines.append('  Confidence histogram:')
        for conf, n in sorted(sc.get('confidences', {}).items()):
            lines.append(f'    {conf:20s} {n}')
        lines.append('')
        lines.append(f'  Pricing-sanity flags:  {sc.get("pricing_flags", 0)}  (see pricing_sanity.csv)')
        lines.append(f'  Column-drift rows:     {sc.get("column_drift_rows", 0)}  (see column_drift.csv)')
        lines.append('')

    if summary.get('errors'):
        lines.append('Errors:')
        for e in summary['errors']:
            lines.append(f'  - {e}')
    (out / 'import_summary.txt').write_text('\n'.join(lines), encoding='utf-8')


# ---------------------------------------------------------------------------
# DB-derived CSVs (queried at the end of the import, before rollback)
# ---------------------------------------------------------------------------

def write_trial_balance(out: Path) -> int:
    """Sum debits/credits per GL account post-import."""
    rows = []
    for acct in GLAccount.objects.order_by('code'):
        agg = JournalLine.objects.filter(account=acct).aggregate(
            d=Sum('debit'), c=Sum('credit'),
        )
        debits = agg['d'] or Decimal('0')
        credits = agg['c'] or Decimal('0')
        balance = debits - credits
        rows.append({
            'account_code': acct.code,
            'name': acct.name,
            'type': acct.type,
            'total_debits': str(debits),
            'total_credits': str(credits),
            'balance': str(balance),
        })
    return _write_csv(
        out / 'trial_balance.csv',
        ['account_code', 'name', 'type', 'total_debits', 'total_credits', 'balance'],
        rows,
    )


def write_ar_aging(out: Path, as_of) -> int:
    rows = []
    for cust in Customer.objects.all().order_by('name'):
        invs = ARInvoice.objects.filter(customer=cust).exclude(status='CANCELLED')
        outstanding = sum(((i.total_amount or 0) - (i.amount_paid or 0)) for i in invs)
        if outstanding == 0:
            continue
        # Bucket each invoice by age relative to as_of
        buckets = {'current': Decimal('0'), '30d': Decimal('0'),
                   '60d': Decimal('0'), '90d': Decimal('0'), 'over_90': Decimal('0')}
        for inv in invs:
            o = (inv.total_amount or Decimal(0)) - (inv.amount_paid or Decimal(0))
            if o <= 0:
                continue
            age_days = (as_of - inv.invoice_date).days
            if age_days <= 0:
                buckets['current'] += o
            elif age_days <= 30:
                buckets['30d'] += o
            elif age_days <= 60:
                buckets['60d'] += o
            elif age_days <= 90:
                buckets['90d'] += o
            else:
                buckets['over_90'] += o
        rows.append({
            'customer_id': cust.id,
            'customer_name': cust.name,
            'total_outstanding': str(outstanding),
            **{k: str(v) for k, v in buckets.items()},
        })
    return _write_csv(
        out / 'ar_aging_after_import.csv',
        ['customer_id', 'customer_name', 'total_outstanding',
         'current', '30d', '60d', '90d', 'over_90'],
        rows,
    )


def write_shopstock(out: Path, qoh_meta: dict) -> int:
    """Cross-check ShopStock against `opening_qty_imported` minus accumulated drains.

    `qoh_meta` is keyed by (inventory_id, variant_id_or_None) with values
    `{opening_qty_imported, sold, fulfilled_layby, credit_lines}`.

    NOTE: this is a CONSISTENCY check between two importer-derived numbers, NOT
    a validation of physical truth. A zero delta means the importer's drains
    matched the importer's opening estimate — it does NOT mean ShopStock is
    physically correct. See stock_opening_audit.csv for confidence per product.
    """
    rows = []
    for stock in ShopStock.objects.select_related('shop', 'inventory_item', 'variant'):
        key = (stock.inventory_item_id, stock.variant_id)
        meta = qoh_meta.get(key, {})
        opening_qty_imported = meta.get('opening_qty_imported', 0)
        sold = meta.get('sold', 0)
        ful = meta.get('fulfilled_layby', 0)
        cr = meta.get('credit_lines', 0)
        qoh_calc = opening_qty_imported - sold - ful - cr
        rows.append({
            'product_code': stock.inventory_item.product_code,
            'name': stock.inventory_item.name[:80],
            'variant_size': (stock.variant.attribute_string if stock.variant else ''),
            'shop_code': stock.shop.code,
            'opening_qty_imported': opening_qty_imported,
            'sold': sold,
            'fulfilled_layby': ful, 'credit_lines': cr,
            'qoh_calc': qoh_calc,
            'shopstock_actual': stock.quantity,
            'delta': stock.quantity - qoh_calc,
        })
    return _write_csv(
        out / 'shopstock_after_import.csv',
        ['product_code', 'name', 'variant_size', 'shop_code',
         'opening_qty_imported', 'sold', 'fulfilled_layby', 'credit_lines',
         'qoh_calc', 'shopstock_actual', 'delta'],
        rows,
    )
