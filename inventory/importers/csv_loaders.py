"""
CSV loaders for the generic client-onboarding importer (import_csv_onboarding).

Unlike excel_loader.py (which decodes the ExoticBlossom workbook's quirky
shapes), these loaders read flat, well-defined CSV templates documented in
data/imports/templates/README.md. Each loader returns (rows, errors):

- rows:   list[dict] of cleaned, typed values — only rows that passed validation
- errors: list[dict] with keys (file, row, field, problem, raw) for the audit pack

A blank line or a line whose every cell is empty is skipped silently.
Headers are matched case-insensitively with surrounding whitespace stripped.
"""
import csv
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path


def _clean(value) -> str:
    return (value or '').strip()


def _to_decimal(value: str, *, allow_empty=True):
    s = _clean(value).replace(',', '').replace('$', '')
    if not s:
        if allow_empty:
            return None
        raise ValueError('required number is empty')
    try:
        return Decimal(s).quantize(Decimal('0.01'))
    except InvalidOperation as exc:
        raise ValueError(f'not a number: {value!r}') from exc


def _to_int(value: str, *, default=None):
    s = _clean(value)
    if not s:
        if default is not None:
            return default
        raise ValueError('required integer is empty')
    try:
        return int(float(s))
    except ValueError as exc:
        raise ValueError(f'not an integer: {value!r}') from exc


def _to_date(value: str, *, required=True) -> date | None:
    s = _clean(value)
    if not s:
        if required:
            raise ValueError('required date is empty')
        return None
    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%m/%d/%Y'):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f'unparseable date: {value!r} (use YYYY-MM-DD)')


def _read(path: Path, required_cols: list[str]) -> tuple[list[dict], list[str]]:
    """Read a CSV into raw dicts with lowercased headers; verify required columns."""
    with path.open(newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            return [], [f'{path.name}: file is empty']
        headers = {h.strip().lower(): h for h in reader.fieldnames if h}
        missing = [c for c in required_cols if c not in headers]
        if missing:
            return [], [f'{path.name}: missing required column(s): {", ".join(missing)}']
        rows = []
        for raw in reader:
            normalized = {h.strip().lower(): (v or '') for h, v in raw.items() if h}
            if not any(_clean(v) for v in normalized.values()):
                continue  # fully blank line
            rows.append(normalized)
        return rows, []


def _err(file: str, row_no: int, field: str, problem: str, raw='') -> dict:
    return {'file': file, 'row': row_no, 'field': field,
            'problem': problem, 'raw': str(raw)[:120]}


# ---------------------------------------------------------------------------
# products.csv
# ---------------------------------------------------------------------------

def load_products_csv(path: Path) -> tuple[list[dict], list[dict]]:
    """product_name, label, size, purchase_cost_per_unit, selling_price,
    opening_stock_qty  [+ landed_cost_per_unit, category, notes]"""
    raw_rows, file_errors = _read(path, ['product_name', 'selling_price', 'opening_stock_qty'])
    errors = [_err(path.name, 0, '', e) for e in file_errors]
    rows = []
    for i, r in enumerate(raw_rows, start=2):  # row 1 = header
        name = _clean(r.get('product_name'))
        if not name:
            errors.append(_err(path.name, i, 'product_name', 'empty'))
            continue
        try:
            selling = _to_decimal(r.get('selling_price'), allow_empty=False)
            purchase = _to_decimal(r.get('purchase_cost_per_unit'))
            landed = _to_decimal(r.get('landed_cost_per_unit'))
            qty = _to_int(r.get('opening_stock_qty'), default=0)
        except ValueError as exc:
            errors.append(_err(path.name, i, 'numeric', str(exc), dict(r)))
            continue
        if qty < 0:
            errors.append(_err(path.name, i, 'opening_stock_qty', 'negative quantity', qty))
            continue
        rows.append({
            'row': i,
            'product_name': name[:100],
            'label': _clean(r.get('label')),
            'size': _clean(r.get('size')).upper(),  # normalised: 'xl' == 'XL'
            'purchase_cost': landed if landed is not None else purchase,
            'selling_price': selling,
            'opening_qty': qty,
            'category': _clean(r.get('category')),
            'notes': _clean(r.get('notes')),
        })
    return rows, errors


# ---------------------------------------------------------------------------
# customers_credit.csv
# ---------------------------------------------------------------------------

def load_customers_credit_csv(path: Path) -> tuple[list[dict], list[dict]]:
    """customer_name, opening_ar_balance, earliest_invoice_date  [+ credit_limit, contact]"""
    raw_rows, file_errors = _read(path, ['customer_name', 'opening_ar_balance', 'earliest_invoice_date'])
    errors = [_err(path.name, 0, '', e) for e in file_errors]
    rows = []
    for i, r in enumerate(raw_rows, start=2):
        name = _clean(r.get('customer_name'))
        if not name:
            errors.append(_err(path.name, i, 'customer_name', 'empty'))
            continue
        try:
            balance = _to_decimal(r.get('opening_ar_balance'), allow_empty=False)
            earliest = _to_date(r.get('earliest_invoice_date'))
            credit_limit = _to_decimal(r.get('credit_limit')) or Decimal('500')
        except ValueError as exc:
            errors.append(_err(path.name, i, 'value', str(exc), dict(r)))
            continue
        if balance <= 0:
            errors.append(_err(path.name, i, 'opening_ar_balance',
                               'balance must be > 0 (only live AR belongs here)', balance))
            continue
        rows.append({
            'row': i,
            'customer_name': name[:200],
            'balance': balance,
            'earliest_invoice_date': earliest,
            'credit_limit': credit_limit,
            'contact': _clean(r.get('contact')),
        })
    return rows, errors


# ---------------------------------------------------------------------------
# open_layby.csv
# ---------------------------------------------------------------------------

def load_open_layby_csv(path: Path) -> tuple[list[dict], list[dict]]:
    """customer_name, purchase_date, total_price, balance_remaining  [+ deposit_paid, item_description]"""
    raw_rows, file_errors = _read(path, ['customer_name', 'purchase_date', 'total_price', 'balance_remaining'])
    errors = [_err(path.name, 0, '', e) for e in file_errors]
    rows = []
    for i, r in enumerate(raw_rows, start=2):
        name = _clean(r.get('customer_name'))
        if not name:
            errors.append(_err(path.name, i, 'customer_name', 'empty'))
            continue
        try:
            purchase_date = _to_date(r.get('purchase_date'))
            total = _to_decimal(r.get('total_price'), allow_empty=False)
            balance = _to_decimal(r.get('balance_remaining'), allow_empty=False)
            deposit = _to_decimal(r.get('deposit_paid')) or Decimal('0')
        except ValueError as exc:
            errors.append(_err(path.name, i, 'value', str(exc), dict(r)))
            continue
        if balance <= 0:
            errors.append(_err(path.name, i, 'balance_remaining',
                               'balance must be > 0 (closed laybys are not imported)', balance))
            continue
        if balance > total:
            errors.append(_err(path.name, i, 'balance_remaining',
                               f'balance {balance} exceeds total_price {total}', dict(r)))
            continue
        rows.append({
            'row': i,
            'customer_name': name[:200],
            'purchase_date': purchase_date,
            'total_price': total,
            'balance': balance,
            'deposit': deposit,
            'item_description': _clean(r.get('item_description')),
        })
    return rows, errors


# ---------------------------------------------------------------------------
# suppliers.csv
# ---------------------------------------------------------------------------

def load_suppliers_csv(path: Path) -> tuple[list[dict], list[dict]]:
    """name  [+ contact_person, phone, email, country]"""
    raw_rows, file_errors = _read(path, ['name'])
    errors = [_err(path.name, 0, '', e) for e in file_errors]
    rows = []
    for i, r in enumerate(raw_rows, start=2):
        name = _clean(r.get('name'))
        if not name:
            errors.append(_err(path.name, i, 'name', 'empty'))
            continue
        rows.append({
            'row': i,
            'name': name[:200],
            'contact_person': _clean(r.get('contact_person'))[:100],
            'phone': _clean(r.get('phone'))[:50],
            'email': _clean(r.get('email')),
            'country': _clean(r.get('country'))[:100] or 'Unknown',
        })
    return rows, errors


# ---------------------------------------------------------------------------
# expenses.csv (optional)
# ---------------------------------------------------------------------------

def load_expenses_csv(path: Path) -> tuple[list[dict], list[dict]]:
    """date, description, amount_usd  [+ category_override, notes]

    category_override, when present, must be one of the Expense model's
    category codes (RENT/UTILITIES/WAGES/FREIGHT/MARKETING/OTHER). Otherwise
    the description is auto-mapped via the cashbook CATEGORY_MAP.
    """
    raw_rows, file_errors = _read(path, ['date', 'description', 'amount_usd'])
    errors = [_err(path.name, 0, '', e) for e in file_errors]
    rows = []
    for i, r in enumerate(raw_rows, start=2):
        desc = _clean(r.get('description'))
        if not desc:
            errors.append(_err(path.name, i, 'description', 'empty'))
            continue
        try:
            when = _to_date(r.get('date'))
            amount = _to_decimal(r.get('amount_usd'), allow_empty=False)
        except ValueError as exc:
            errors.append(_err(path.name, i, 'value', str(exc), dict(r)))
            continue
        if amount <= 0:
            errors.append(_err(path.name, i, 'amount_usd', 'must be > 0', amount))
            continue
        rows.append({
            'row': i,
            'date': when,
            'description': desc[:255],
            'amount': amount,
            'category_override': _clean(r.get('category_override')).upper(),
            'notes': _clean(r.get('notes')),
        })
    return rows, errors
