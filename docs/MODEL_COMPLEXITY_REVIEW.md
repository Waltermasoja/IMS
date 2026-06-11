# Model Complexity Review — Post-Launch Refactor Backlog

**Date:** 2026-06-11 · **Status:** documentation only — NO pre-launch model changes.

The question prompting this review: "are the models too complicated for a
2-shop POS?" Short answer: the schema is ~40 models where ~30 would do, but
**none of the over-engineered pieces are safely deletable before launch** —
each is still wired into active views. This doc is the post-launch worklist.

## Verified-in-use (cannot delete yet, despite looking redundant)

| Model | Looks like | Actually used by |
|---|---|---|
| `Sales` (legacy single-row sale) | superseded by SalesTicket/SalesLine | `make_sale` POS endpoint, `sales_summary`, `sales_report_simple`, `per_product`, dashboard recents — [inventory/views.py:172,384,520,585](../inventory/views.py) |
| `SalesInvoice` + `SalesInvoiceItem` | duplicates ARInvoice + SalesTicket | `inventory/invoice_views.py` (email/print invoice flow) |
| `missing_inventory` | duplicates `Damaged` | referenced in `inventory/views.py` + admin |
| `BankReconciliation` | manual recon, rarely needed at this scale | `accounting/views.py` + forms + admin |

## Refactor sequence (post-launch)

### Phase 1 — unify the sales write path (highest value)
1. Point the legacy "Quick Sale" modal at `checkout_ticket` (SalesTicket) instead of `make_sale` (Sales).
2. Migrate `sales_summary` / `sales_report_simple` / `per_product` to query `SalesLine`.
3. Stop writing `Sales`; keep the table read-only for history; drop in a later release.
   Also drops: `Inventory.sales_record` M2M (write-only, never queried).

### Phase 2 — one stock source of truth
`ShopStock` vs `Inventory.quantity_in_Stock` / `ProductVariant.quantity_in_stock`
are dual-written today. Pick `ShopStock` (it's shop-scoped, which the business
needs), make the legacy fields computed/read-only, then drop them.
**Prerequisite:** the physical stocktake workflow (`apply_stocktake`) must be
in place because CLO opening quantities are LOW-confidence estimates.

### Phase 3 — flatten the variant attribute system
`AttributeType` + `AttributeValue` + two M2M tables exist to model exactly one
attribute in practice (Size; Color/Material are seeded but unused by the
importer and POS). Replace with a `size` CharField on `ProductVariant` (or a
small JSONField if a second attribute ever materialises). Saves 4 tables and
the per-variant M2M queries (`attribute_string` does 1 query per variant today).

### Phase 4 — collapse invoice triplication
`SalesTicket` (receipt) / `ARInvoice` (receivable) / `SalesInvoice` (printable
invoice) → keep the first two, render printable invoices from `SalesTicket`.

### Phase 5 — small deletions once confirmed dead
- `missing_inventory` → merge into `Damaged` (same shape, same GL posting)
- `BankReconciliation` → drop unless the accountant asks for it
- `LaybyItem` → JSONField on `LaybyPlan` (line items never queried independently)
- `Supplier.total_orders` / `total_spent` — denormalised fields nothing updates; drop or wire up
- `SalesTicket.cashier_summary` / `DailyCashUp.cashier_summary` JSON — derivable from queries

## What we deliberately did pre-launch instead

- N+1 fixes via annotation (`inventory_list`, `product_variants_list`, `sales_summary`) — see git history 2026-06-11
- Pagination on all long lists
- Accountant exports (AR aging, layby register, expense ledger)
- CSV onboarding path (`import_csv_onboarding`) so Baby Bazaar's go-live does not depend on any refactor
