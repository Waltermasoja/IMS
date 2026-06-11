# Shop Onboarding CSV Templates

Fill these files in to bring a new shop onto IMS. Only **products.csv** is
required — the others are optional and can be skipped if the shop has no
credit customers, laybys, suppliers, or recorded expenses yet.

Run (dry-run first, then with `--commit`):

```bash
python manage.py import_csv_onboarding \
    --dir data/imports/babybazaar/ \
    --shop-code BBY \
    --as-of 2026-07-01 \
    --commit
```

Every run writes an audit pack to `media/imports/{timestamp}/`:
`import_summary.txt`, `import_errors.csv` (rows that were skipped and why),
`trial_balance.csv`, and `ar_aging_after_import.csv`. **Review
import_errors.csv after the dry-run before committing.**

## Rules that apply to every file

- All money is **USD**. No other currencies.
- Dates are **YYYY-MM-DD** (2026-07-01). DD/MM/YYYY is tolerated but not preferred.
- The header row must be present and spelled as shown (case doesn't matter).
- Blank lines are ignored. A row with a problem is **skipped and logged**, it
  does not stop the import.

## products.csv (required)

One row per product — or one row per size if the product comes in sizes.
Rows sharing the same `product_name` + `label` are merged into one product
with one variant per size.

| Column | Required | Meaning |
|---|---|---|
| product_name | yes | What the item is ("Baby grow white cotton") |
| label | no | Brand ("Carters") — used to group and to build the product code |
| size | no | Size value (0-3M, XL, 42…). Leave empty for no-size products. Sizes are upper-cased, so "xl" and "XL" are the same variant |
| purchase_cost_per_unit | no* | What you paid per unit |
| selling_price | yes | Shelf price. A product without a price cannot be sold in the POS |
| opening_stock_qty | yes | Units on hand **as of the --as-of date** (not historical purchases) |
| landed_cost_per_unit | no | Cost including freight/duty — overrides purchase_cost when present |
| category | no | Free text ("Baby Clothing") — categories are created automatically |
| notes | no | Internal note |

*Strongly recommended: without a cost, profit reports for that product are
meaningless and it is left out of the opening-stock journal value.

**Accounting:** one journal entry is posted for the whole file —
Dr 1300 Inventory / Cr 3000 Owner's Equity at cost. Suppress with
`--skip-stock-je` if the accountant prefers to post it manually.

## customers_credit.csv (optional)

Only customers who **currently owe money**. One row per customer with the
single rolled-up balance — not per-invoice detail.

| Column | Required | Meaning |
|---|---|---|
| customer_name | yes | Full name |
| opening_ar_balance | yes | What they owe as of --as-of. Must be > 0 |
| earliest_invoice_date | yes | When the oldest unpaid purchase happened (drives the aging report) |
| credit_limit | no | Default 500 |
| contact | no | Phone number |

**Accounting:** per customer — an opening AR invoice plus
Dr 1200 Accounts Receivable / Cr 3100 Retained Earnings.
Old, uncollectable debts should NOT be listed here — write them off in the
old records instead.

## open_layby.csv (optional)

Only laybys that are **still being paid off** (balance > 0). Closed laybys
stay in the old records.

| Column | Required | Meaning |
|---|---|---|
| customer_name | yes | Reuses the customer if one with the same name exists |
| purchase_date | yes | When the layby was opened. Due date is set to +90 days |
| total_price | yes | Full price of the goods |
| balance_remaining | yes | Still owed. Must be > 0 and ≤ total_price |
| deposit_paid | no | Initial deposit (informational) |
| item_description | no | What was put on layby (informational) |

**Accounting:** no journal entry is posted (deposit dates are unknown). If
the balance sheet must show the unearned-revenue liability for amounts
already paid, the accountant posts one manual JE:
Dr 3000 Owner's Equity / Cr 2300 Unearned Revenue for the total paid-so-far.

## suppliers.csv (optional)

| Column | Required |
|---|---|
| name | yes |
| contact_person, phone, email, country | no |

## expenses.csv (optional)

Expenses **since the --as-of date** that should appear in this month's P&L.
Don't list older expenses — they belong to the old records.

| Column | Required | Meaning |
|---|---|---|
| date | yes | |
| description | yes | Auto-mapped to a category by keywords (rent, salaries, freight, electricity…) |
| amount_usd | yes | |
| category_override | no | One of RENT / UTILITIES / WAGES / FREIGHT / MARKETING / OTHER — use when the auto-map can't tell |
| notes | no | |

Rows that can't be mapped land in import_errors.csv — add a
`category_override` and re-run. Stock purchases do NOT go here (they're
inventory, not expenses — use an Import Order in the app instead). Owner
drawings and personal spending don't go here either.

## What NOT to collect from the client

- Historical sales — the system starts fresh from the --as-of date
- Per-invoice AR detail — one rolled-up balance per customer is enough
- Old stocktake counts — only the current count matters
- Foreign-currency amounts — convert to USD before filling in
- Paid-off laybys and settled debts
