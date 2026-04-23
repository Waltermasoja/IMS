# IMS Implementation Roadmap

## Guiding principles
- Pre-launch, empty DB → free to reshape schema, squash migrations at the end
- VAT-inclusive shelf prices, single rate in settings (default 15%), zero-rated flag per product for exemptions
- One Z-report per shop per day, sales tagged with cashier
- Accountant: read-only app login + Excel/CSV/PDF exports
- ZIMRA fiscalisation deferred — build clean VAT math now so FDMS integration is a later thin layer

## Phase A — Foundations (schema reshape while DB is empty)

**A1. Shop model + per-shop stock**
- New `Shop` model (name, code, address, phone, is_active).
- New `ShopStock` join table (shop, inventory_item, variant, quantity, reorder_point).
- Update `Inventory.quantity_in_Stock` to be a computed property summing across shops.
- Add `UserProfile.default_shop` FK.
- Stamp shop FK on: Sales, StockMovement, Return, Damaged, missing_inventory, CashbookEntry, Expense.
- New `StockTransfer` model for moving stock.
*(Note: All models should be in separate files as per user rule)*

**A2. Tender types on Sales**
- Split `Sales.payment_method` into `tender_type` and `terms`.
- Add GL accounts for Cash-on-Hand, EcoCash Float, Bank Current Account.
- Update `accounting/utils.py` for correct tender account posting.
- Add `tender_reference` for reconciliation.

**A3. Cart-based POS data model**
- Promote `Sales` to `SalesTicket` (header) + `SalesLine` (lines).
- Rewrite sales posting to iterate lines.

## Phase B — POS & mobile experience
**B1. Cart-based mobile-first POS**
- Rewrite POS interface to proper cart flow.
- Touch-friendly tap targets.
- Replace hardcoded $ with currency_symbol.
- Host Inter font locally.

**B2. PWA install**
- Add manifest.json and app icons.
- Minimal service worker for caching.

**B3. Barcodes**
- Add barcode field to Inventory and ProductVariant.
- Auto-generate barcodes and add label print page.

## Phase C — VAT & compliance
**C1. VAT-inclusive pricing**
- Add VAT rate and inclusive toggle to SiteSettings.
- Add VAT exemption flags to Inventory/ProductVariant.
- Calculate VAT at sale.

**C2. VAT reports**
- VAT output, input, and return summary reports.

## Phase D — Cash-up, reconciliation, reports
**D1. Daily Z-report**
- Z-reports by shop and day.
- Lock mechanism to close day.

**D2. EcoCash & bank reconciliation**
- Extend bank_reconciliation for EcoCash CSV import.

**D3. Accountant hand-off**
- Read-only accountant role and exports (CSV/Excel/PDF).

## Phase E — Returns, exchanges, damages
**E1. Proper returns**
- Rebuild Return model linked to SalesTicket/SalesLine.
- Post reversing GL entry.

**E2. Exchanges**
- Exchange = return line + new line.

**E3. Damages with GL posting**
- Post Dr Inventory Loss / Cr Inventory for damages.

## Phase F — Stocking trips & procurement
**F1. StockingTrip wrapper**
- Group import orders into trips.
- Allocate trip expenses across orders.

**F2. Trip profitability report**
- Landed cost vs revenue-to-date by trip.

**F3. Foreign supplier AP in USD**
- AP aging in USD.

## Phase G & H — Nice-to-haves & Housekeeping
- Promotions, credit applications, dashboard widgets.
- Gitignore cleanup, code smells, tests, and squash migrations.
