"""One-shot data patches for the 2026-march-exoticblossom workbook.

These overrides correct specific cells that had data-entry errors in the
source workbook (typos, blank dates, Excel epoch placeholders). They are
applied during sheet load so the workbook file itself stays unchanged
(saving via openpyxl would wipe Excel's cached formula values across the
credit-clients / layby / cashbook sheets and break the import).

Format: { row_number: replacement_date }
"""
from datetime import date

DAILY_SALES_DATE_OVERRIDES: dict[int, date] = {
    132: date(2026, 1, 25),
}

CREDIT_CLIENTS_DATE_OVERRIDES: dict[int, date] = {
    409: date(2025, 12, 31),
    567: date(2026, 4, 24),
    579: date(2026, 4, 28),
}
