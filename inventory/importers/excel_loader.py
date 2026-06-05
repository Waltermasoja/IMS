"""
Pure-read openpyxl wrappers for the ExoticBlossom workbook.

No DB writes here — each function opens the workbook in read-only / data-only
mode, iterates rows, normalises values, and returns a plain list of dicts.
The orchestrator can call these once and hand the results to phase modules.

Column indices are 0-based throughout (matching openpyxl values_only tuples).

Sheet → function mapping
------------------------
  dresses / jkts & jerserys / suits / hats shoes & bags  → load_product_sheet()
  stock purchase 2026                                      → load_stock_purchase()
  daily sales                                              → load_daily_sales()
  credit clients                                           → load_credit_clients()
  layby clients                                            → load_layby_clients()
  cashbook                                                 → load_cashbook()
  STOCK TAKE                                               → load_stock_take()  (audit only)

Analytical / budget sheets (Budget, cashflow, cash budget, sales analysis,
sops, salaries, stock movement) are not imported — skip them.
"""
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import openpyxl


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _open(workbook_path: str):
    return openpyxl.load_workbook(workbook_path, read_only=True, data_only=True)


def _to_decimal(value: Any) -> Decimal | None:
    """Convert to a 2dp Decimal — matches accounting fields' decimal_places=2.

    JournalLine.debit/credit (and most monetary fields) use decimal_places=2,
    and full_clean() rejects greater precision. The 4dp precision used in
    earlier drafts only mattered for FX rates, which are passed as Decimal
    literals from --zig-rate, not from this function.
    """
    if value is None:
        return None
    try:
        return Decimal(str(value)).quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError):
        return None


def _to_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%m/%d/%Y'):
            try:
                return datetime.strptime(value.strip(), fmt).date()
            except ValueError:
                continue
    return None


def _clean_str(value: Any) -> str:
    if value is None:
        return ''
    return str(value).strip()


def _clean_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _is_section_header(description: str) -> bool:
    """Heuristic: all-uppercase short strings are category headers, not products.

    Examples treated as headers (skipped):
      "BALL GOWNS", "JACKETS", "OUTFITS & SUITS", "MAY 2019 STOCK".
    """
    d = description.strip()
    if not d:
        return True
    if d == d.upper() and len(d) < 60:
        return True
    return False


# ---------------------------------------------------------------------------
# Product sheets (dresses / jkts & jerserys / suits / hats shoes & bags)
#
# Actual column layout per the workbook header row (0-based):
#   1  SHOP                    - shop tag (often None — inherit from --shop-code)
#   2  LABEL                   - brand / label name
#   3  Q                       - PER-ROW SEQUENCE NUMBER (NOT stock count!).
#                                Values increment 1..N across every row, so we
#                                MUST NOT use it as quantity. Real qty is
#                                derived from (total purchase price / pur price).
#   4  size                    - size value (numeric or XS/S/M/L/XL/XXL)
#   5  Item                    - product description (may also be a section header)
#   7  pur price               - purchase price per unit (USD)
#   8  total purchase price    - pur_price * units_bought  (qty derived from this)
#   9  total cost              - landed extension (incl. freight + duty)
#  10  Indirect Cost / unit    - per-unit overhead
#  11  Total Unit Cost         - landed cost per unit
#  14  Actual Price            - actual selling price used
#  15  SALE                    - units sold to date (informational)
#  16  S/T JAN '25             - prior-year stock take snapshot
#  17  s/take jan2026          - current stock take snapshot
# ---------------------------------------------------------------------------

_PRODUCT_SHEETS = {
    'dresses':           {'category': 'dresses'},
    'jkts & jerserys':   {'category': 'jackets_jerseys'},
    'suits':             {'category': 'suits'},
    'hats shoes & bags': {'category': 'hats_shoes_bags'},
}


def _derive_qty(pur_price, total_pur_price) -> int | None:
    """Stock count = round(total purchase price / per-unit purchase price).

    Currently UNUSED by the category-sheet loader (per user decision each row
    is one physical item, so qty=1). Kept here for the stock_purchase loader
    fallback when the explicit qnty column is empty.

    Returns None when either operand is missing or pur_price is zero.
    """
    if pur_price is None or total_pur_price is None:
        return None
    if pur_price <= 0:
        return None
    return int((total_pur_price / pur_price).quantize(Decimal('1')))


# Expected per-column types for the category sheets. Used by
# validate_product_sheet_columns() to emit column_drift.csv.
_PRODUCT_SHEET_SCHEMA = {
    # column_index: (column_name, allowed types)
    1:  ('SHOP',                 (str, type(None))),
    2:  ('LABEL',                (str, type(None))),
    3:  ('Q',                    (int, float, type(None))),
    4:  ('size',                 (str, int, float, type(None))),
    5:  ('Item',                 (str, type(None))),
    7:  ('pur price',            (int, float, type(None))),
    8:  ('total purchase price', (int, float, type(None))),
    10: ('Indirect Cost / unit', (int, float, type(None))),
    11: ('Total Unit Cost',      (int, float, type(None))),
    14: ('Actual Price',         (int, float, type(None))),
    15: ('SALE',                 (int, float, type(None))),
    16: ('S/T JAN \'25',         (int, float, type(None))),
    17: ('s/take jan2026',       (int, float, type(None))),
}


def validate_product_sheet_columns(workbook_path: str) -> list[dict]:
    """Return rows whose cell types don't match the expected column schema.

    One drift row per offending cell. Helps catch shifted columns (e.g. a row
    where the description landed in the size column because someone inserted
    a column mid-sheet).
    """
    drifts: list[dict] = []
    wb = _open(workbook_path)
    for sheet_name in _PRODUCT_SHEETS:
        if sheet_name not in wb.sheetnames:
            continue
        ws = wb[sheet_name]
        for i, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            # Skip rows that are entirely blank or look like section dividers.
            if not row or all(c is None for c in row[:18]):
                continue
            desc = _clean_str(row[5]) if len(row) > 5 else ''
            if not desc or _is_section_header(desc):
                continue
            for idx, (col_name, allowed) in _PRODUCT_SHEET_SCHEMA.items():
                if idx >= len(row):
                    continue
                val = row[idx]
                if not isinstance(val, allowed):
                    drifts.append({
                        'sheet': sheet_name,
                        'row': i,
                        'column_index': idx,
                        'column_name': col_name,
                        'expected_type': '|'.join(t.__name__ for t in allowed),
                        'actual_value': repr(val)[:60],
                        'actual_type': type(val).__name__,
                    })
    wb.close()
    return drifts


def load_product_sheet(workbook_path: str, sheet_name: str) -> list[dict]:
    """Return normalised product rows from one category sheet."""
    rows = []
    wb = _open(workbook_path)
    if sheet_name not in wb.sheetnames:
        wb.close()
        return rows

    ws = wb[sheet_name]
    category = _PRODUCT_SHEETS.get(sheet_name, {}).get('category', sheet_name)

    for i, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if len(row) < 9:
            continue

        description = _clean_str(row[5])
        if not description or _is_section_header(description):
            continue

        pur_price = _to_decimal(row[7]) if len(row) > 7 else None
        total_pur_price = _to_decimal(row[8]) if len(row) > 8 else None
        # Skip rows that look like memos (no price, no description). Already
        # filtered above by description check; the price check is a tighter
        # guard against label/header rows.
        if pur_price is None and total_pur_price is None:
            continue

        # Default opening-quantity per row is 1 (one physical item per row).
        # stock_signals.derive_group_quantities() may override this per
        # (label, description, size) using the lot-once or stock-take signals.
        quantity = 1

        rows.append({
            'sheet':           sheet_name,
            'category':        category,
            'shop_tag':        _clean_str(row[1]),
            'label':           _clean_str(row[2]),
            'quantity':        quantity,
            'size':            _clean_str(row[4]),
            'description':     description,
            'purchase_price':  pur_price,
            'total_pur_price': total_pur_price,                                   # col 8 — lot total (repeated)
            'indirect_cost':   _to_decimal(row[10]) if len(row) > 10 else None,   # col 10
            'total_unit_cost': _to_decimal(row[11]) if len(row) > 11 else None,   # col 11 — landed cost
            'selling_price':   _to_decimal(row[14]) if len(row) > 14 else None,   # col 14 — Actual Price
            'sale_realized':   _to_decimal(row[15]) if len(row) > 15 else None,   # col 15 — SALE (realised price)
            'stock_take_2025': _clean_int(row[16])  if len(row) > 16 else None,   # col 16 — S/T JAN '25
            'stock_take_2026': _clean_int(row[17])  if len(row) > 17 else None,   # col 17 — s/take jan2026
            'purchase_date':   None,           # date column is sheet-dependent / unreliable
            'status':          '',
            'row_index':       i,
        })

    wb.close()
    return rows


def load_all_product_sheets(workbook_path: str) -> list[dict]:
    """Convenience: load all four category sheets into one combined list."""
    out = []
    for sheet_name in _PRODUCT_SHEETS:
        out.extend(load_product_sheet(workbook_path, sheet_name))
    return out


# ---------------------------------------------------------------------------
# stock purchase 2026
#
# Column layout (0-based):
#  1  shop, 2  label, 4  qnty, 5  size, 6  Item,
#  8  purchase price / unit $, 11 Indirect Cost / unit, 12 Total Unit Cost,
# 15 Actual Price, 19 date.
# ---------------------------------------------------------------------------

def load_stock_purchase(workbook_path: str) -> list[dict]:
    """Return rows from the 'stock purchase 2026' sheet."""
    sheet_name = 'stock purchase 2026'
    rows = []
    wb = _open(workbook_path)
    if sheet_name not in wb.sheetnames:
        wb.close()
        return rows

    ws = wb[sheet_name]
    for i, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if len(row) < 9:
            continue

        description = _clean_str(row[6])
        if not description or _is_section_header(description):
            continue

        # qnty column (4) is rarely filled. Fall back to derived qty from
        # (total purchase price / pur price), then to 1 (each row = one item).
        pur_price = _to_decimal(row[8])  if len(row) > 8  else None
        total_pur_price = _to_decimal(row[9]) if len(row) > 9 else None
        quantity = (
            _clean_int(row[4])
            or _derive_qty(pur_price, total_pur_price)
            or 1
        )

        rows.append({
            'sheet':           sheet_name,
            'category':        'stock_purchase_2026',
            'shop_tag':        _clean_str(row[1]),
            'label':           _clean_str(row[2]),
            'quantity':        quantity,
            'size':            _clean_str(row[5]),
            'description':     description,
            'purchase_price':  pur_price,
            'indirect_cost':   _to_decimal(row[11]) if len(row) > 11 else None,
            'total_unit_cost': _to_decimal(row[12]) if len(row) > 12 else None,
            'selling_price':   _to_decimal(row[15]) if len(row) > 15 else None,
            'purchase_date':   _to_date(row[19])    if len(row) > 19 else None,
            'status':          '',
            'row_index':       i,
        })

    wb.close()
    return rows


# ---------------------------------------------------------------------------
# daily sales
#
# Column layout (0-based):
#  0  date
#  1  USD cash SALE        - amount for cash sale
#  2  USD POS SALE         - amount for card/POS sale
#  3  ZIG POS SALE         - ZIG POS amount (caller converts via --zig-rate)
#  4  item description     - free text (fuzzy matched)
#  5  CASH                 - cash tender column (sometimes duplicates col 1)
#  6  POS                  - pos tender column (sometimes duplicates col 2)
#  7  layby sale cost      - **layby SALE INITIATION amount** (full selling price
#                            of items reserved); row may also have an instalment
#                            in col[8]/col[9] on the same line — these stack.
#  8  layby inst/deposit cash
#  9  layby inst/deposit debit
# 10  credit sale cost     - **credit SALE INITIATION amount** (creates an
#                            AR receivable for the full price; not a COGS field).
# 11  credit sale payment CASH
# 12  credit sale payment DEBIT
# 13  DISC                 - discount
#
# Date carries forward across blank rows (it spans multiple rows in the sheet).
# A row is a sale when col[4] is non-empty.
# ---------------------------------------------------------------------------

def load_daily_sales(workbook_path: str) -> list[dict]:
    """Return raw daily-sales rows. Caller decides tender + matches descriptions."""
    sheet_name = 'daily sales'
    rows = []
    wb = _open(workbook_path)
    if sheet_name not in wb.sheetnames:
        wb.close()
        return rows

    ws = wb[sheet_name]
    current_date: date | None = None

    from inventory.importers.patches import DAILY_SALES_DATE_OVERRIDES

    for i, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if len(row) < 5:
            continue

        cell_date = _to_date(row[0])
        if i in DAILY_SALES_DATE_OVERRIDES:
            cell_date = DAILY_SALES_DATE_OVERRIDES[i]
        if cell_date is not None:
            current_date = cell_date

        description = _clean_str(row[4])
        if not description:
            continue

        def _d(idx):
            return _to_decimal(row[idx]) if len(row) > idx else None

        rows.append({
            'sheet':       sheet_name,
            'row_index':   i,
            'date':        current_date,
            'description': description,
            'usd_cash':    _d(1),
            'usd_pos':     _d(2),
            'zig_pos':     _d(3),
            'tender_cash':    _d(5),
            'tender_pos':     _d(6),
            'layby_initial':  _d(7),    # full selling price when a layby is opened
            'layby_cash':     _d(8),
            'layby_card':     _d(9),
            'credit_initial': _d(10),   # full selling price for a new credit sale
            'credit_cash':    _d(11),
            'credit_card':    _d(12),
            'discount':       _d(13),
        })

    wb.close()
    return rows


# ---------------------------------------------------------------------------
# credit clients
#
# Sheet name has a trailing space in the workbook ("credit clients ").
# One block per customer: name in col[1] on the first row, subsequent rows
# carry the same customer's invoice/payment lines.
#
# Column layout (0-based):
#  1  customer name (only on first row of block)
#  2  date of purchase
#  3  inv no.
#  4  amount
#  5  paid to date    (negative values = payments already received)
#  8  USD Bal 2024    — outstanding balance as of end-2024 (the figure we use)
# ---------------------------------------------------------------------------

def load_credit_clients(workbook_path: str) -> list[dict]:
    """Return one dict per credit client: name, earliest date, total invoiced, balance."""
    rows = []
    wb = _open(workbook_path)

    # Workbook has trailing space; tolerate either spelling
    actual_name = next((sn for sn in wb.sheetnames if sn.strip() == 'credit clients'), None)
    if actual_name is None:
        wb.close()
        return rows

    ws = wb[actual_name]
    current_customer: str | None = None
    current_start_row: int = 0
    invoice_rows: list[dict] = []

    def _flush(name: str, inv_rows: list[dict], start: int) -> dict | None:
        if not name:
            return None
        balance = None
        earliest_date = None
        total_amount = Decimal('0')
        for r in inv_rows:
            if r['balance'] is not None:
                balance = r['balance']  # last non-null wins (rolling carry-forward)
            if r['date'] is not None:
                if earliest_date is None or r['date'] < earliest_date:
                    earliest_date = r['date']
            if r['amount'] is not None:
                total_amount += r['amount']
        return {
            'customer_name':         name,
            'earliest_invoice_date': earliest_date,
            'total_invoiced':        total_amount,
            'outstanding_balance':   balance,
            'row_index':             start,
            'invoice_rows':          inv_rows,
        }

    for i, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if len(row) < 5:
            continue

        name_cell = _clean_str(row[1]) if len(row) > 1 else ''
        if name_cell and name_cell != current_customer:
            if current_customer:
                result = _flush(current_customer, invoice_rows, current_start_row)
                if result:
                    rows.append(result)
            current_customer = name_cell
            current_start_row = i
            invoice_rows = []

        if current_customer is None:
            continue

        from inventory.importers.patches import CREDIT_CLIENTS_DATE_OVERRIDES

        row_date = _to_date(row[2]) if len(row) > 2 else None
        if i in CREDIT_CLIENTS_DATE_OVERRIDES:
            row_date = CREDIT_CLIENTS_DATE_OVERRIDES[i]
        inv_row = {
            'date':    row_date,
            'inv_no':  _clean_str(row[3])  if len(row) > 3 else '',
            'amount':  _to_decimal(row[4]) if len(row) > 4 else None,
            'paid':    _to_decimal(row[5]) if len(row) > 5 else None,
            'balance': _to_decimal(row[8]) if len(row) > 8 else None,
        }
        if any(v is not None and v != '' for v in inv_row.values()):
            invoice_rows.append(inv_row)

    if current_customer:
        result = _flush(current_customer, invoice_rows, current_start_row)
        if result:
            rows.append(result)

    wb.close()
    return rows


# ---------------------------------------------------------------------------
# layby clients
#
# Column layout (0-based):
#  1  date of purchase, 3  name, 4  inv no, 5  invoice total,
#  6  deposit, 7  inst, 9  layby bal.
#
# Sheet structure: each customer occupies 2-N rows. The first row has the
# customer NAME and purchase_date; later rows in the block have instalment
# dates only; the LAST row in the block has the totals (no name, but
# invoice_total + deposit + final layby_balance). We accumulate per-block
# state and emit one entry per block whose final balance > 0.
# ---------------------------------------------------------------------------

def load_layby_clients(workbook_path: str) -> list[dict]:
    """Return active layby plans (balance > 0). Multi-row blocks per customer."""
    sheet_name = 'layby clients'
    rows: list[dict] = []
    wb = _open(workbook_path)
    if sheet_name not in wb.sheetnames:
        wb.close()
        return rows

    ws = wb[sheet_name]

    current_name: str | None = None
    current_start: int = 0
    current_date = None
    current_inv_no: str | None = None
    current_invoice_total = None
    current_deposit = None
    current_instalment = None

    def _flush(balance) -> None:
        if not current_name:
            return
        if balance is None or balance <= 0:
            return
        rows.append({
            'sheet':         sheet_name,
            'row_index':     current_start,
            'purchase_date': current_date,
            'customer_name': current_name,
            'inv_no':        current_inv_no,
            'invoice_total': current_invoice_total,
            'deposit':       current_deposit,
            'instalment':    current_instalment,
            'layby_balance': balance,
        })

    for i, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if len(row) < 10:
            continue

        name = _clean_str(row[3])
        balance = _to_decimal(row[9])

        # New customer block begins when col[3] holds a name. Capture the
        # opening data for this customer; balance / totals row will come later.
        if name:
            # Flush previous block if it ended without a separate totals row
            # (rare; e.g. final block in sheet missing its summary).
            _flush(None)
            current_name = name
            current_start = i
            current_date = _to_date(row[1])
            current_inv_no = _clean_str(row[4])
            current_invoice_total = _to_decimal(row[5])
            current_deposit = _to_decimal(row[6])
            current_instalment = _to_decimal(row[7])
            continue

        # Mid-block instalment row: refresh totals if columns are present
        # (the LAST row in a block carries the final totals + balance).
        invoice_total = _to_decimal(row[5])
        deposit = _to_decimal(row[6])
        instalment = _to_decimal(row[7])
        if invoice_total is not None:
            current_invoice_total = invoice_total
        if deposit is not None:
            current_deposit = deposit
        if instalment is not None:
            current_instalment = instalment

        # A non-null balance marks the end of the block — emit and reset.
        if balance is not None:
            _flush(balance)
            current_name = None  # don't double-emit for the same block

    # Tail flush in case the final block had its balance in the last row above.
    _flush(None)

    wb.close()
    return rows


# ---------------------------------------------------------------------------
# cashbook
#
# This workbook's cashbook only uses the EXPENDITURE side of the layout:
# the receipt columns (2-6: cash USD / debit card / ecocash / converted ZIG /
# TOTAL) are entirely empty. All payment data lives in cols 9-12.
#
# Column layout (0-based) — actual data columns:
#  9  description / category text   (e.g. "city of harare licence 2026")
# 10  cash payment amount           (regular USD payments)
# 11  personal                      (owner draws / personal use — archive only)
# 12  occasional sub-total / converted-ZIG amount
#
# Date inference: there is NO date column. Dates are encoded as month-header
# rows where col[9] reads like "JANUARY 2026..", "FEBRUARY 2026", etc.
# All rows under a month header inherit that header's first-of-month date.
# ---------------------------------------------------------------------------

_MONTH_NAMES = {
    'january', 'february', 'march', 'april', 'may', 'june',
    'july', 'august', 'september', 'october', 'november', 'december',
}

_MONTH_INDEX = {name: i + 1 for i, name in enumerate(
    ['january', 'february', 'march', 'april', 'may', 'june',
     'july', 'august', 'september', 'october', 'november', 'december'])}


def _is_month_header(text: str) -> bool:
    lower = text.lower()
    return any(m in lower for m in _MONTH_NAMES) and len(text) < 40


def _parse_month_header(text: str, default_year: int | None = None) -> date | None:
    """Extract a first-of-month date from headers like 'JANUARY 2026..'.

    If the header omits the year (e.g. bare 'FEBRUARY '), fall back to
    `default_year`. Callers should track the most-recent year-bearing header
    and pass it in so successive bare month headers inherit the right year.
    """
    lower = text.lower()
    month_no = next((idx for name, idx in _MONTH_INDEX.items() if name in lower), None)
    if month_no is None:
        return None
    year_match = re.search(r'\b(20\d{2})\b', text)
    if year_match:
        return date(int(year_match.group(1)), month_no, 1)
    if default_year is not None:
        return date(default_year, month_no, 1)
    return None


def load_cashbook(workbook_path: str) -> list[dict]:
    """Return cashbook expense rows with description, inferred month-date, amount."""
    sheet_name = 'cashbook'
    rows = []
    wb = _open(workbook_path)
    if sheet_name not in wb.sheetnames:
        wb.close()
        return rows

    ws = wb[sheet_name]
    current_date: date | None = None
    current_year: int | None = None

    # Cashbook descriptions live in col[9]; payment amounts in col[10] (cash)
    # and col[11] (personal). Receipts side (cols 2-6) is empty in this workbook.
    DESC_COL = 9
    CASH_COL = 10
    PERSONAL_COL = 11
    EXTRA_COL = 12   # occasional sub-totals / converted ZIG

    for i, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if len(row) <= DESC_COL:
            continue

        description = _clean_str(row[DESC_COL])
        if not description:
            continue

        # Month-header rows update the running date and are NOT data rows.
        # Bare month names ("FEBRUARY ", "MARCH") inherit the year from the
        # most-recent year-bearing header so successive months don't all
        # collapse onto the first month's date.
        if _is_month_header(description):
            parsed = _parse_month_header(description, default_year=current_year)
            if parsed is not None:
                current_date = parsed
                current_year = parsed.year
            continue

        if description.lower() in ('total', 'totals', 'balance', 'net',
                                   'inflows', 'outflows', 'expenditure'):
            continue

        def _d(idx):
            return _to_decimal(row[idx]) if len(row) > idx else None

        cash     = _d(CASH_COL)
        personal = _d(PERSONAL_COL)
        extra    = _d(EXTRA_COL)

        if not any(v is not None for v in (cash, personal, extra)):
            # Section sub-headers (e.g. "rentals & opc", "salaries & transport")
            # have no amount; they are data-less group labels — skip silently.
            continue

        amount = cash if cash is not None else (extra if extra is not None else personal)

        rows.append({
            'sheet':       sheet_name,
            'row_index':   i,
            'date':        current_date,
            'description': description,
            # Receipt-side columns (2-6) are empty in this workbook layout —
            # included as None so the cashbook phase's existing keys still work.
            'cash':        cash,
            'card':        None,
            'ecocash':     None,
            'zig_usd':     extra,
            'personal':    personal,   # owner draw — phase will route to archive
            'amount':      amount,
        })

    wb.close()
    return rows


# ---------------------------------------------------------------------------
# STOCK TAKE  (audit-only — for cross-check, not loaded into live tables)
# ---------------------------------------------------------------------------

def load_stock_take(workbook_path: str) -> list[dict]:
    """Return stock-take rows for audit purposes only."""
    sheet_name = 'STOCK TAKE'
    rows = []
    wb = _open(workbook_path)
    if sheet_name not in wb.sheetnames:
        wb.close()
        return rows

    ws = wb[sheet_name]
    # Header is at row 4; data from row 5 onwards
    for i, row in enumerate(ws.iter_rows(min_row=5, values_only=True), start=5):
        if len(row) < 5:
            continue
        description = _clean_str(row[2])
        if not description or _is_section_header(description):
            continue
        rows.append({
            'sheet':          sheet_name,
            'row_index':      i,
            'label':          _clean_str(row[1]),
            'description':    description,
            'purchase_price': _to_decimal(row[3]),
            'sale_price':     _to_decimal(row[4]),
        })

    wb.close()
    return rows
