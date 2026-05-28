# IMS Pro — Inventory Management System

A Django-based multi-shop retail system: POS, inventory, import orders, and
full double-entry accounting in one package. Built for Zimbabwean retail
(VAT-inclusive pricing, multi-tender including EcoCash, USD-dominant with
FX-aware import orders).

---

## What's in the box

- **Multi-shop POS** — cart-based, mobile-first, shop-scoped stock, tender
  routing (Cash / EcoCash / Bank Transfer / Card), installable as a PWA.
- **Full GL accounting** — double-entry journal with idempotent posting,
  balanced-entry enforcement, and a per-shop or consolidated P&L.
- **Sales terms** — Immediate, On Account (AR), or Layby, all posting
  correctly to the right accounts at the right time.
- **VAT compliance** — VAT-inclusive shelf pricing, per-product exempt
  flag, 15% default rate, VAT return report with output/input breakdown.
- **Import orders with landed cost** — supplier orders with shipping,
  customs and freight allocated across items (value/quantity/weight/smart);
  landed cost flows into product purchase price.
- **Stocking trips** — group import orders from a buying trip; trip-level
  travel expenses allocate across orders; trip P&L + sell-through.
- **Daily Z-report** — close the trading day per shop; aggregates by
  tender and cashier; counted-cash vs expected variance; sequential
  Z-number per shop.
- **Returns + damages** — ticket-based partial returns with pro-rata GL
  reversal and refund tender routing; damage writes to Inventory Loss.
- **Accountant handoff** — Excel exports (GL detail, trial balance, sales
  tickets) + CSV + dedicated read-only `accountant` role.
- **EcoCash / bank reconciliation** — upload statement CSV, auto-match
  to tickets by `tender_reference` + amount.

---

## Tech stack

- **Backend:** Django 5.0 · Python 3.12 · SQLite (dev) / MySQL or
  PostgreSQL (prod)
- **Frontend:** Django templates · Tailwind CSS · Alpine.js · Font Awesome
- **Docs/exports:** openpyxl (Excel), python-barcode (Code-128),
  weasyprint (PDF, optional)
- **Static hosting:** WhiteNoise · PWA manifest + service worker

---

## Quick start

```bash
# 1. Clone + enter
git clone <repo> && cd IMS

# 2. Venv + deps
python3.12 -m venv imsvenv
source imsvenv/bin/activate
pip install -r requirements.txt

# 3. Migrate + seed
python manage.py migrate
python manage.py init_gl_accounts          # creates the chart of accounts
python manage.py createsuperuser

# 4. Create at least one Shop (admin panel) — POS requires a shop

# 5. Run
python manage.py runserver
```

Key URLs:
- `/` → redirects to login
- `/inventory/pos/` → POS
- `/inventory/cashup/<shop_id>/` → daily Z-report
- `/accounting/` → accounting dashboard
- `/accounting/reports/vat/` → VAT return
- `/accounting/exports/` → accountant Excel exports
- `/admin/` → Django admin

---

## High-level architecture

Two Django apps — deliberate boundary between physical stock flow and
financial accounting flow.

```
inventory/                                accounting/
├── Shop, ShopStock, StockTransfer        ├── GLAccount, JournalEntry, JournalLine
├── Inventory, ProductVariant             ├── ARInvoice, ARPayment
├── SalesTicket, SalesLine   ──────▶      ├── LaybyPlan, LaybyItem, LaybyPayment
├── Return, Damaged, missing_inventory    ├── CashbookEntry, BankReconciliation
├── ImportOrder, ImportOrderItem, etc.    ├── Expense
├── StockingTrip                          └── utils.py (post_ticket, etc.)
├── DailyCashUp (Z-report)
├── Customer, Supplier, UserProfile
└── SiteSettings
```

**The posting contract:** anything that moves money must go through
`accounting.utils.post_ticket()` (or `post_damaged_goods`,
`post_return_from_ticket`). These enforce balanced JE, shop stamping,
VAT split, and idempotency via `posted_to_gl` / `posted_to_cashbook` /
`stock_posted` flags.

---

## Revenue recognition by sale terms

A `SalesTicket` has two orthogonal axes:

1. **`terms`** — when revenue is recognised and whether AR is created.
2. **`tender_type`** — which tender account receives the money.

| Terms      | When sold                                     | When paid / fulfilled                      |
|------------|-----------------------------------------------|--------------------------------------------|
| IMMEDIATE  | Dr Tender, Cr Revenue + VAT, Dr COGS, Cr Inv  | (same time)                                |
| CREDIT     | Dr AR, Cr Revenue + VAT, Dr COGS, Cr Inv       | AR payment: Dr Cash, Cr AR                 |
| LAYBY      | Dr AR, Cr Unearned Revenue, stock reserved    | Fulfillment: Dr Unearned, Cr Revenue + VAT |

Tender routing (via `accounting.utils.get_tender_account`):
`CASH → 1000`, `ECOCASH → 1010`, `BANK_TRANSFER/CARD → 1020`.

---

## Chart of accounts (seed)

Run `python manage.py init_gl_accounts` once. Key codes:

| Code | Account                        | Type       |
|------|--------------------------------|------------|
| 1000 | Cash on Hand                   | ASSET      |
| 1010 | EcoCash Float                  | ASSET      |
| 1020 | Bank Current Account           | ASSET      |
| 1200 | Accounts Receivable            | ASSET      |
| 1300 | Inventory                      | ASSET      |
| 2300 | Unearned Revenue (layby)       | LIAB       |
| 2400 | Output VAT Payable             | LIAB       |
| 4000 | Sales Revenue                  | INCOME     |
| 5000 | Cost of Goods Sold             | EXP        |
| 5100 | Inventory Loss (damage/shrink) | EXP        |
| 6000–6900 | Operating expenses        | EXP        |

The command is idempotent — it updates renamed accounts, skips unchanged,
creates missing.

---

## User roles

`UserProfile.role`:

| Role        | POS | Inventory | Reports | Accounting | Admin |
|-------------|:---:|:---------:|:-------:|:----------:|:-----:|
| `admin`     | ✅  | ✅        | ✅      | ✅         | ✅    |
| `manager`   | ✅  | ✅        | ✅      | ✅         | —     |
| `sales`     | ✅  | —         | —       | —          | —     |
| `accountant`| —   | —         | ✅      | ✅ (RO)    | —     |
| `viewer`    | —   | RO        | ✅      | RO         | —     |

Per-user overrides exist for `can_make_sales`, `can_process_returns`,
`can_apply_discounts`, `max_discount_percent`, `default_shop`.

---

## Multi-shop model

- **`Shop`** — one row per retail location. Has `code` (e.g. `BBY`,
  `CLO`), optional `vat_number_override` for future per-shop VAT
  registration.
- **`ShopStock`** — join table `(shop, inventory_item, variant) → qty`.
  This is the **source of truth for stock**, not `Inventory.quantity_in_Stock`.
- Most operational models carry a nullable `shop` FK:
  - Nullable on `JournalEntry`, `Expense`, `CashbookEntry` — `NULL` means
    consolidated / corporate (e.g. accounting fees).
  - Non-null on `SalesTicket`, `ARInvoice`, `LaybyPlan` — always tied
    to a specific shop.
- **`StockTransfer`** moves stock between shops with a single atomic
  `execute()` that writes two `StockMovement` rows (OUT + IN).

Per-shop P&L: filter `JournalEntry.shop=X`. Consolidated: no filter.

---

## Development commands

```bash
# Run tests (14 core tests in inventory/tests.py)
python manage.py test inventory

# Create migrations after model changes
python manage.py makemigrations

# Apply
python manage.py migrate

# Verify nothing drifted
python manage.py check
python manage.py makemigrations --check

# Django shell for ad-hoc queries
python manage.py shell

# Rebuild Tailwind CSS (watch mode during UI work)
npx tailwindcss -i ./static/css/input.css -o ./static/css/output.css --watch
```

---

## Project layout

```
IMS/
├── inventorySystem/         Django project config (settings, root urls)
├── inventory/               Core app: stock, POS, import orders, returns
│   ├── models.py            Shop, Inventory, SalesTicket, StockingTrip, etc.
│   ├── views.py             POS, cash-up, returns, product search AJAX
│   ├── admin.py
│   ├── tests.py             14 tests covering Phase A-F
│   └── management/commands/ init_gl_accounts, etc.
├── accounting/              GL, AR, layby, cashbook, VAT, exports
│   ├── models.py            GLAccount, JournalEntry, ARInvoice, LaybyPlan…
│   ├── utils.py             post_ticket + per-terms helpers (core logic)
│   └── views.py             Dashboard, reports, VAT, reconciliation, exports
├── templates/               Shared templates (Tailwind + Alpine)
├── static/                  CSS/JS + PWA manifest + service worker
├── docs/                    Feature-specific guides (layby, imports, etc.)
├── CLAUDE.md                Instructions for Claude Code when working here
└── requirements.txt
```

---

## Configuration

`inventorySystem/settings.py`:

- **`DEBUG`** — `False` in production.
- **`SECRET_KEY`** — change before deploy.
- **`ALLOWED_HOSTS`** — add your domain (or `.onrender.com` for Render).
- **`DATABASES`** — SQLite by default; switch to MySQL / PostgreSQL via
  environment variables for production.

Runtime settings live in `SiteSettings` (singleton) — VAT rate, currency
symbol, tax registration number, receipt footer, etc. Edit via admin or
the Site Settings page.

---

## Testing

The test suite (`inventory/tests.py`) validates the critical financial
flows on SQLite:

```bash
python manage.py test inventory
# Ran 14 tests in ~1.5s — OK
```

Coverage:
- VAT back-out from inclusive prices (taxable and exempt lines)
- IMMEDIATE / CREDIT / LAYBY ticket posting
- Tender routing (Cash → 1000, EcoCash → 1010, etc.)
- Idempotent posting (second call is a no-op)
- Credit limit enforcement
- Stock transfers between shops
- Pro-rata return reversal + refund
- Damage GL posting at cost
- Daily cash-up sequential Z-numbers
- Shop isolation (sales at BBY don't drain CLO stock)

---

## Deployment

The repo ships with `render.yaml` and `Procfile` for Render deployment.

Pre-launch checklist:
- [ ] `DEBUG = False`, rotate `SECRET_KEY`, set `ALLOWED_HOSTS`
- [ ] Point `DATABASES` at MySQL/PostgreSQL
- [ ] `python manage.py collectstatic` (WhiteNoise serves them)
- [ ] `python manage.py migrate`
- [ ] `python manage.py init_gl_accounts`
- [ ] Create `Shop` rows for each retail location
- [ ] Create users, set each user's `default_shop`

---

## Further reading (in `docs/`)

- `FIXES_AND_SETUP.md` — troubleshooting and first-time setup
- `LAYBY_AND_CREDIT_SALES_ACCOUNTING.md` — full accounting flow per terms
- `IMPORT_ORDER_GUIDE.md` — landed cost and supplier workflow
- `INVOICE_SYSTEM_GUIDE.md` — invoice and AR system
- `DEPLOYMENT.md` — Render deployment notes

`CLAUDE.md` is guidance for the Claude Code agent working in this repo.

---

## Licence

Proprietary — internal use only. Not for redistribution.
