"""
ExoticBlossom Excel → IMS importer package.

Each module handles one source sheet (or one cross-cutting concern). The
orchestrator lives in `inventory/management/commands/import_exoticblossom.py`
and runs the phases inside one `transaction.atomic()` block.

Phase order matters and is enforced by the orchestrator:

    1. Pre-flight checks (require_empty, GL accounts present, etc.)
    2. products.py        — Inventory + ProductVariant + opening ShopStock
    3. ar.py              — Customer + opening ARInvoice + bad-debt write-offs
    4. layby.py           — active LaybyPlan + LaybyItem (linked via AR helper)
    5. sales.py           — SalesTicket + SalesLine; pre-cutoff to HistoricalRecord,
                            post-cutoff posted via accounting.utils.post_ticket()
    6. cashbook.py        — Expense + CashbookEntry (post-cutoff only); pre to archive
    7. historical.py      — final flush of any deferred archive rows
    8. audit.py           — emit reconciliation CSVs

See `/home/kudzai/.claude/plans/lets-properly-go-through-zazzy-tide.md` for the
full plan, decision rationale, and risk register.
"""

LOG_PREFIX = '[IMPORT-EB]'   # ExoticBlossom — distinct from existing [IMPORT] prefix
