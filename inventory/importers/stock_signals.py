"""
Opening-stock derivation from the ExoticBlossom category sheets.

The workbook never committed to a single meaning for "quantity-on-hand". This
module makes the disagreement *explicit* — for every (label, description, size)
it picks the best available signal, tags the chosen tier + confidence, and
exposes the underlying numbers so the operator can audit and override before
go-live.

Tiers (highest signal wins)
---------------------------
1. STOCK_TAKE_2026  — col 17 's/take jan2026' has a positive integer
                       → confidence HIGH (manual physical count)
2. STOCK_TAKE_2025  — col 16 'S/T JAN '25' has a positive integer
                       → confidence MED (12-month-stale physical count)
3. LOT_DISTRIBUTED  — pur_price + total_pur_price both present AND the implied
                       lot size passes a sanity cap. lot_units = total/pur is
                       computed once per (pur_price, total_pur_price) group
                       (because the workbook repeats the same lot total on
                       every row of the lot). lot_units is then split across
                       the lot's sizes weighted by row count per size.
                       → confidence MED if lot_units ≈ rows_in_lot, LOW otherwise
4. ROW_COUNT        — final fallback: 1 unit per row, summed per size.
                       → confidence VERY_LOW

Sanity cap on LOT_DISTRIBUTED
-----------------------------
If `lot_units > max(2 × rows_in_lot, rows_in_lot + 20)` the lot is REJECTED
and the row falls through to ROW_COUNT with `lot_rejected_reason` populated.
This catches the bayker-black pattern (40 rows, lot_total=6149, pur=1.65 →
3727 implied units which is 93× the row count — clearly a lot-header repeated
across line entries, not a per-row purchase).

Audit row shape
---------------
Every (label, description, size) yields one audit dict written to
`stock_opening_audit.csv` by audit.py. Each dict carries:

  product_code, label, description, size, tier, confidence,
  opening_qty_imported, pur_price, total_pur_price, lot_units_raw,
  rows_in_lot, rows_for_this_size, lot_rejected_reason

product_code is filled by the caller after the Inventory record is created
(stock_signals doesn't know product codes, it operates on workbook rows).
"""
from collections import defaultdict
from decimal import Decimal


TIER_STOCK_TAKE_2026 = 'STOCK_TAKE_2026'
TIER_STOCK_TAKE_2025 = 'STOCK_TAKE_2025'
TIER_LOT_DISTRIBUTED = 'LOT_DISTRIBUTED'
TIER_ROW_COUNT = 'ROW_COUNT'

CONFIDENCE_HIGH = 'HIGH'
CONFIDENCE_MED = 'MED'
CONFIDENCE_LOW = 'LOW'
CONFIDENCE_VERY_LOW = 'VERY_LOW'


def _derive_lot_units(pur_price, total_pur_price) -> int | None:
    """Return implied lot size from total_pur_price ÷ pur_price, or None."""
    if pur_price is None or total_pur_price is None:
        return None
    if pur_price <= 0:
        return None
    return int((total_pur_price / pur_price).quantize(Decimal('1')))


def _lot_sanity_reason(lot_units: int, rows_in_lot: int) -> str | None:
    """Return rejection reason if the lot fails the sanity cap, else None."""
    if lot_units <= 0:
        return f'lot_units<=0 ({lot_units})'
    cap = max(2 * rows_in_lot, rows_in_lot + 20)
    if lot_units > cap:
        return (
            f'lot_units={lot_units} > cap={cap} '
            f'(rows_in_lot={rows_in_lot}) — likely a lot total repeated per row'
        )
    return None


def derive_group_quantities(
    groups: dict[tuple[str, str], list[dict]],
) -> tuple[dict[tuple[str, str, str], int], list[dict]]:
    """Compute per-(label, description, size) opening qty + audit trail.

    Args:
        groups: keyed by (label, description) → list of row dicts loaded by
                excel_loader.load_product_sheet. Sizes are pre-normalised
                (upper-cased, stripped) before this is called.

    Returns:
        size_qty:   {(label, description, size): qty (int)}
        audit_rows: list[dict] — one entry per (label, description, size),
                    with tier + confidence + evidence fields. product_code
                    starts blank; the caller backfills it.
    """
    size_qty: dict[tuple[str, str, str], int] = {}
    audit_rows: list[dict] = []

    for (label, description), rows in groups.items():
        # Sub-group rows by (pur_price, total_pur_price). The workbook repeats
        # the same lot-total on every row of a lot, so the (pur, total) tuple
        # IS the lot identifier.
        lot_buckets: dict[tuple, list[dict]] = defaultdict(list)
        for r in rows:
            key = (r.get('purchase_price'), r.get('total_pur_price'))
            lot_buckets[key].append(r)

        for (pur_price, total_pur_price), lot_rows in lot_buckets.items():
            rows_in_lot = len(lot_rows)

            # Count rows per size within this lot.
            size_rows: dict[str, list[dict]] = defaultdict(list)
            for r in lot_rows:
                size_rows[r.get('size') or ''].append(r)

            # Compute lot-once stats for the audit (even if we don't use it).
            lot_units_raw = _derive_lot_units(pur_price, total_pur_price)
            lot_rejected_reason = (
                _lot_sanity_reason(lot_units_raw, rows_in_lot)
                if lot_units_raw is not None else 'no pur/total prices'
            )

            for size, srows in size_rows.items():
                rows_for_this_size = len(srows)

                # ── Tier 1: stock_take_2026 ─────────────────────────────────
                st26 = next((r.get('stock_take_2026') for r in srows
                             if r.get('stock_take_2026') is not None), None)
                if st26 is not None and st26 > 0:
                    qty = int(st26)
                    tier = TIER_STOCK_TAKE_2026
                    confidence = CONFIDENCE_HIGH
                    chosen_reason = None
                # ── Tier 2: stock_take_2025 ─────────────────────────────────
                elif (st25 := next((r.get('stock_take_2025') for r in srows
                                    if r.get('stock_take_2025') is not None), None)) is not None and st25 > 0:
                    qty = int(st25)
                    tier = TIER_STOCK_TAKE_2025
                    confidence = CONFIDENCE_MED
                    chosen_reason = None
                # ── Tier 3: lot-distributed (if sanity passes) ──────────────
                elif lot_units_raw is not None and lot_rejected_reason is None:
                    # Distribute lot across sizes weighted by row count.
                    share = rows_for_this_size / rows_in_lot if rows_in_lot else 0
                    qty = max(1, round(lot_units_raw * share))
                    tier = TIER_LOT_DISTRIBUTED
                    # If lot_units is close to rows_in_lot (within 50%),
                    # treat as MED. Otherwise LOW — could be a stale lot
                    # whose stock has since been mostly sold.
                    if abs(lot_units_raw - rows_in_lot) <= rows_in_lot * 0.5:
                        confidence = CONFIDENCE_MED
                    else:
                        confidence = CONFIDENCE_LOW
                    chosen_reason = None
                # ── Tier 4: row count fallback ──────────────────────────────
                else:
                    qty = rows_for_this_size
                    tier = TIER_ROW_COUNT
                    confidence = CONFIDENCE_VERY_LOW
                    chosen_reason = lot_rejected_reason

                size_key = (label, description, size)
                # Aggregate across lot buckets sharing the same size (rare —
                # would mean a (label, desc, size) appears in two different
                # price lots).
                size_qty[size_key] = size_qty.get(size_key, 0) + qty

                audit_rows.append({
                    'product_code': '',              # backfilled by caller
                    'label': label,
                    'description': description,
                    'size': size,
                    'tier': tier,
                    'confidence': confidence,
                    'opening_qty_imported': qty,
                    'pur_price': str(pur_price) if pur_price is not None else '',
                    'total_pur_price': str(total_pur_price) if total_pur_price is not None else '',
                    'lot_units_raw': lot_units_raw if lot_units_raw is not None else '',
                    'rows_in_lot': rows_in_lot,
                    'rows_for_this_size': rows_for_this_size,
                    'lot_rejected_reason': chosen_reason or '',
                })

    return size_qty, audit_rows


def derive_pricing_sanity(rows: list[dict]) -> list[dict]:
    """Scan rows and flag suspicious price relationships.

    Flags:
      LOSS:          sale_realized < pur_price  (selling below cost)
      DEEP_DISCOUNT: |selling_price - sale_realized| / selling_price > 0.30
                      where both are filled (heavy markdown signal)
      MISSING_SELL:  pur_price set, selling_price blank (no shelf price)

    Each returned dict carries enough context to action the row.
    """
    out: list[dict] = []
    for r in rows:
        pur = r.get('purchase_price')
        sell = r.get('selling_price')
        sale = r.get('sale_realized')
        sheet = r.get('sheet', '')
        row_idx = r.get('row_index', '')
        label = r.get('label', '')
        desc = r.get('description', '')[:60]

        if pur is not None and sell is None:
            out.append({
                'flag': 'MISSING_SELL',
                'sheet': sheet, 'row': row_idx,
                'label': label, 'description': desc,
                'pur_price': str(pur), 'selling_price': '',
                'sale_realized': str(sale) if sale is not None else '',
                'detail': 'pur_price set but no Actual Price (col 14)',
            })

        if sale is not None and pur is not None and sale < pur:
            out.append({
                'flag': 'LOSS',
                'sheet': sheet, 'row': row_idx,
                'label': label, 'description': desc,
                'pur_price': str(pur),
                'selling_price': str(sell) if sell is not None else '',
                'sale_realized': str(sale),
                'detail': f'SALE {sale} < pur_price {pur} — selling below cost',
            })

        if sale is not None and sell is not None and sell > 0:
            delta = abs(sell - sale) / sell
            if delta > Decimal('0.30'):
                out.append({
                    'flag': 'DEEP_DISCOUNT',
                    'sheet': sheet, 'row': row_idx,
                    'label': label, 'description': desc,
                    'pur_price': str(pur) if pur is not None else '',
                    'selling_price': str(sell),
                    'sale_realized': str(sale),
                    'detail': f'SALE {sale} differs from Actual Price {sell} by {delta:.0%}',
                })

    return out
