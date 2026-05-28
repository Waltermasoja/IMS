"""
HistoricalRecord writer.

Pre-cutoff rows (date < `--cutoff`) are NOT loaded into live tables. Instead
each row is JSON-archived in the `HistoricalRecord` model so the operator
can still inspect it via a `/history/` view, but it never touches the GL,
AR, layby, or stock tables.

Key rule from plan R7: cashbook entries with date < cutoff MUST be archived
here, not via `Expense.objects.create()`, because `Expense.save()` auto-posts
back-dated journal entries that would corrupt the GL.
"""
from datetime import date, datetime
from decimal import Decimal

from inventory.models import HistoricalRecord


def _json_safe(value):
    """Convert openpyxl row values into JSON-serialisable forms."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def archive_row(
    *,
    sheet_name: str,
    row_index: int,
    row_data: dict,
    record_date: date | None = None,
    shop=None,
    source_workbook: str = '',
    counter: dict | None = None,
) -> HistoricalRecord:
    """Persist one source row as a HistoricalRecord. Returns the saved instance.

    `counter` is an optional dict the caller may pass to tally per-sheet archive
    counts (used by audit.py for `historical_archive_summary.csv`).
    """
    safe = {k: _json_safe(v) for k, v in (row_data or {}).items()}
    record = HistoricalRecord.objects.create(
        sheet_name=sheet_name,
        row_index=row_index,
        row_data=safe,
        record_date=record_date,
        shop=shop,
        source_workbook=source_workbook,
    )
    if counter is not None:
        counter[sheet_name] = counter.get(sheet_name, 0) + 1
    return record


def bulk_archive(records: list[dict], counter: dict | None = None) -> int:
    """Bulk-create historical rows. `records` is a list of dicts shaped like
    archive_row's kwargs. Returns count created.
    """
    instances = []
    for r in records:
        safe = {k: _json_safe(v) for k, v in (r.get('row_data') or {}).items()}
        instances.append(HistoricalRecord(
            sheet_name=r['sheet_name'],
            row_index=r['row_index'],
            row_data=safe,
            record_date=r.get('record_date'),
            shop=r.get('shop'),
            source_workbook=r.get('source_workbook', ''),
        ))
        if counter is not None:
            counter[r['sheet_name']] = counter.get(r['sheet_name'], 0) + 1

    HistoricalRecord.objects.bulk_create(instances, batch_size=500)
    return len(instances)
