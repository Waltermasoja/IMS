"""
Shared run context for the ExoticBlossom importer.

`RunContext` is the single object every phase module receives. The
orchestrator builds it once at command start and threads it through
phases in order. Phase modules MUST NOT instantiate or mutate fields
they don't own — see the field comments below for ownership.

Ownership rules
---------------
- `workbook_path`, `shop`, `cutoff`, `ar_cutoff`, `zig_rate`,
  `fuzzy_threshold`, `commit`, `out_dir`, `log`, `source_workbook`,
  `cashier_user` are read-only inputs set by the orchestrator.

- `historical_counter`, `qoh_meta`, `fuzzy_matcher`, `unmatched_sales`,
  `bad_debt_writeoffs`, `opening_ar_journal`, `unmappable_expenses`,
  `negative_qoh` are mutable shared collectors. Specific phases write
  to specific collectors:

    products.py       writes  qoh_meta, fuzzy_matcher
    ar.py             writes  bad_debt_writeoffs, opening_ar_journal
    sales.py          reads   fuzzy_matcher, qoh_meta
                       writes  unmatched_sales, qoh_meta (drains)
    cashbook.py       writes  unmappable_expenses
    historical writes (any phase) update historical_counter
    audit.py (final)  reads everything; emits CSVs

- `counts` is the per-phase tally dict surfaced in `import_summary.txt`.
  Each phase increments its own keys (e.g. `counts['products_created']`).

Phase contract
--------------
Every phase module exposes ONE callable:

    def run(ctx: RunContext) -> None: ...

It logs progress via `ctx.log(msg)` and updates the shared collectors.
Errors are raised; the orchestrator decides whether to abort.
"""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

from inventory.importers.fuzzy import FuzzyMatcher


@dataclass
class RunContext:
    # ---------- Inputs (orchestrator-owned, treat as read-only) ----------
    workbook_path: str
    shop: Any                               # inventory.models.Shop
    cutoff: date                            # live-data cutoff (default 2026-01-01)
    ar_cutoff: date                         # AR cutoff (default 2025-01-01)
    zig_rate: Decimal                       # ZIG → USD rate
    fuzzy_threshold: int
    commit: bool
    out_dir: Path                           # media/imports/{ts}/
    log: Callable[[str], None]
    source_workbook: str                    # basename for HistoricalRecord
    cashier_user: Any                       # imported_history User instance

    # ---------- Shared mutable collectors (phase-owned) ----------
    historical_counter: dict[str, int] = field(default_factory=dict)
    # qoh_meta key: (inventory_id, variant_id_or_None)
    # value: {'opening_qty_imported': int, 'sold': int, 'fulfilled_layby': int, 'credit_lines': int}
    # NOTE: opening_qty_imported is the importer's BEST-EFFORT estimate of
    # opening stock — NOT a verified physical count. The workbook column 'Q'
    # is a per-row sequence number, not a quantity; do not confuse the two.
    qoh_meta: dict[tuple, dict[str, int]] = field(default_factory=dict)
    fuzzy_matcher: FuzzyMatcher | None = None

    unmatched_sales: list[dict] = field(default_factory=list)
    bad_debt_writeoffs: list[dict] = field(default_factory=list)
    bad_debt_recoveries: list[dict] = field(default_factory=list)
    opening_ar_journal: list[dict] = field(default_factory=list)
    unmappable_expenses: list[dict] = field(default_factory=list)
    negative_qoh: list[dict] = field(default_factory=list)

    # Plan A audit artefacts (Plan A demo polish)
    stock_opening_audit: list[dict] = field(default_factory=list)
    pricing_sanity: list[dict] = field(default_factory=list)
    column_drift: list[dict] = field(default_factory=list)

    # ---------- Per-phase tally for the operator summary ----------
    counts: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def bump(self, key: str, n: int = 1) -> None:
        self.counts[key] = self.counts.get(key, 0) + n

    def qoh_get(self, inventory_id: int, variant_id: int | None) -> dict[str, int]:
        """Return (creating if absent) the per-product drain dict."""
        key = (inventory_id, variant_id)
        slot = self.qoh_meta.get(key)
        if slot is None:
            slot = {'opening_qty_imported': 0, 'sold': 0,
                    'fulfilled_layby': 0, 'credit_lines': 0}
            self.qoh_meta[key] = slot
        return slot
