"""
Dry-run / rollback orchestration for the ExoticBlossom importer.

The orchestrator runs all DB writes inside one `transaction.atomic()` block.
At the end, if `--commit` was not passed, we raise `DryRunRollback` to roll
back every write. The reconciliation CSVs are still emitted (they are written
via plain file I/O, intentionally outside the transaction) so the operator
can review what the importer *would have done*.

See plan risks R1, R2, R5 for non-rollback-safe operations to avoid.
"""
from contextlib import contextmanager

from django.db import connections, transaction


class DryRunRollback(Exception):
    """Raised at the end of a dry-run to force the atomic block to roll back."""


class ImportAborted(Exception):
    """Raised when a pre-flight check fails (e.g. tables not empty, GL missing)."""


@contextmanager
def transactional_run(commit: bool, log):
    """Wrap an importer phase in a transaction. Roll back if commit is False.

    Usage:
        with transactional_run(commit=options['commit'], log=stdout) as ctx:
            run_phases(ctx)

    The yielded value is the same `commit` flag — phases shouldn't depend on
    it, but a few audit calls do.
    """
    # Plan R6 — disable per-connection conn_max_age for the duration of this
    # command so a long Railway dry-run doesn't hit a stale-connection retry
    # mid-transaction. Cheap; harmless on SQLite.
    try:
        connections['default'].settings_dict['CONN_MAX_AGE'] = 0
    except Exception:
        pass

    try:
        with transaction.atomic():
            yield commit
            if not commit:
                log('[IMPORT-EB] Dry-run complete — rolling back all DB writes.')
                raise DryRunRollback('Dry-run mode (no --commit flag).')
            log('[IMPORT-EB] Commit phase: changes will be retained.')
    except DryRunRollback:
        # Expected — silenced so the command exits cleanly.
        log('[IMPORT-EB] Rollback complete. Reconciliation CSVs are still on disk.')


def update_dates(model_class, pk, **date_fields):
    """Bypass `auto_now_add=True` to set real historical dates on imported rows.

    Plan R1 — `LaybyPlan.created_date`, `ARInvoice.created_date`,
    `CashbookEntry.created_date`, `JournalEntry.posted_at`, etc. all use
    `auto_now_add=True`, which silently ignores `created_date=...` passed to
    the constructor. The fix is to update via the queryset *after* create:

        plan = LaybyPlan.objects.create(...)
        update_dates(LaybyPlan, plan.pk, created_date=real_date)

    `update()` bypasses `auto_now_add` (it's only honoured by `save()`).
    """
    if not date_fields:
        return
    model_class.objects.filter(pk=pk).update(**date_fields)
