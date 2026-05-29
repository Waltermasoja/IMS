"""
ExoticBlossom Excel → IMS importer (Django management command).

This is the orchestrator. It owns the `transaction.atomic()` block, builds
the shared `RunContext`, runs each phase in fixed order, and emits the
reconciliation audit pack to media/imports/{ts}/.

USAGE
-----

    python manage.py import_exoticblossom \
        --workbook "/path/to/2026 march exoticblossom.xlsx" \
        --shop-code CLO \
        --cutoff 2026-01-01 \
        --ar-cutoff 2025-01-01 \
        --zig-rate 25.5081 \
        --fuzzy-threshold 85 \
        --require-empty \
        [--commit]

Without --commit, ALL DB writes are rolled back at the end of the run, but
the audit pack is still written (file I/O is intentionally outside the
transaction so dry-run review is possible).

PHASE ORDER (enforced)
----------------------
    1. Pre-flight checks (require_empty, GL accounts present, shop exists)
    2. products  — Inventory + ProductVariant + ShopStock + fuzzy corpus
    3. ar        — Customer + opening AR + bad-debt write-offs
    4. layby     — active LaybyPlan + LaybyItem
    5. sales     — SalesTicket + SalesLine; pre-cutoff archived
    6. cashbook  — Expense + auto-posted JEs (post-cutoff only)
    7. audit     — emit reconciliation CSVs + import_summary.txt

See `/home/kudzai/.claude/plans/lets-properly-go-through-zazzy-tide.md` for
the full plan, decision rationale, and risk register.
"""
import os
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils.dateparse import parse_date

from accounting.models import ARInvoice, JournalEntry, LaybyPlan
from accounting.utils import MissingGLAccountError, require_gl
from inventory.importers import LOG_PREFIX
from inventory.importers import audit, ar, cashbook, layby, products, sales
from inventory.importers.context import RunContext
from inventory.importers.dry_run import DryRunRollback, ImportAborted, transactional_run
from inventory.importers.fuzzy import FuzzyMatcher
from inventory.models import (
    Customer, HistoricalRecord, Inventory, ProductVariant, SalesTicket, Shop,
)


User = get_user_model()


REQUIRED_GL_CODES = ['1000', '1200', '1300', '2100', '3100', '4000', '5000',
                     '6000', '6100', '6200', '6300', '6400', '6500', '6900']

# Tables that must be empty when --require-empty is passed. Listed in order
# from leaf-most to root-most so a non-empty error message points at the
# most-specific offender first.
REQUIRED_EMPTY_MODELS = [
    SalesTicket, ARInvoice, LaybyPlan, JournalEntry,
    Inventory, ProductVariant, Customer, HistoricalRecord,
]


class Command(BaseCommand):
    help = 'Import the ExoticBlossom Excel workbook into IMS (dry-run by default).'

    def add_arguments(self, parser):
        parser.add_argument('--workbook', required=True,
                            help='Absolute path to the .xlsx workbook.')
        parser.add_argument('--shop-code', required=True,
                            help="Shop code (e.g. 'CLO') the imported data belongs to.")
        parser.add_argument('--cutoff', default='2026-01-01',
                            help='Live-data cutoff (YYYY-MM-DD). Rows before this are archived.')
        parser.add_argument('--ar-cutoff', default='2025-01-01',
                            help='AR cutoff (YYYY-MM-DD). Customers older than this are written off.')
        parser.add_argument('--zig-rate', default='25.5081',
                            help='ZIG → USD conversion rate.')
        parser.add_argument('--fuzzy-threshold', type=int, default=85,
                            help='rapidfuzz token_set_ratio cutoff (0–100).')
        parser.add_argument('--require-empty', action='store_true',
                            help='Abort if target tables are not empty.')
        parser.add_argument('--force', action='store_true',
                            help='Bypass --require-empty (use with caution).')
        parser.add_argument('--commit', action='store_true',
                            help='Commit DB changes. Without this flag, the run is a dry-run.')

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def handle(self, *args, **options):
        workbook = options['workbook']
        if not os.path.isfile(workbook):
            raise CommandError(f'Workbook not found: {workbook}')

        cutoff = parse_date(options['cutoff'])
        ar_cutoff = parse_date(options['ar_cutoff'])
        if not cutoff or not ar_cutoff:
            raise CommandError('--cutoff and --ar-cutoff must be YYYY-MM-DD.')

        try:
            zig_rate = Decimal(options['zig_rate'])
        except (ValueError, TypeError) as exc:
            raise CommandError(f'Invalid --zig-rate: {exc}') from exc

        # Pre-flight 1 — shop must exist
        try:
            shop = Shop.objects.get(code=options['shop_code'].upper())
        except Shop.DoesNotExist as exc:
            raise CommandError(
                f"Shop with code '{options['shop_code']}' not found. "
                f"Run: python manage.py create_initial_shops"
            ) from exc

        # Pre-flight 2 — required GL accounts must exist
        try:
            for code in REQUIRED_GL_CODES:
                require_gl(code)
        except MissingGLAccountError as exc:
            raise CommandError(
                f"{exc}\nRun: python manage.py init_gl_accounts"
            ) from exc

        # Pre-flight 3 — placeholder cashier user must exist
        try:
            cashier = User.objects.get(username='imported_history')
        except User.DoesNotExist as exc:
            raise CommandError(
                "User 'imported_history' not found. "
                "Run: python manage.py seed_imported_history_user"
            ) from exc

        # Pre-flight 4 — require-empty check (plan R4)
        if options['require_empty'] and not options['force']:
            self._assert_target_tables_empty()

        # Build the audit run dir BEFORE entering the transaction so the
        # path is stable for the operator even on rollback.
        timestamp = datetime.utcnow()
        out_dir = audit.make_run_dir(timestamp)

        log = self._make_logger()
        log(f'{LOG_PREFIX} Starting import')
        log(f'{LOG_PREFIX} Workbook   : {workbook}')
        log(f'{LOG_PREFIX} Shop       : {shop.code} ({shop.name})')
        log(f'{LOG_PREFIX} Cutoff     : {cutoff} (live data >= this date)')
        log(f'{LOG_PREFIX} AR cutoff  : {ar_cutoff} (live AR >= this date)')
        log(f'{LOG_PREFIX} ZIG rate   : {zig_rate}')
        log(f'{LOG_PREFIX} Fuzzy thr  : {options["fuzzy_threshold"]}')
        log(f'{LOG_PREFIX} Mode       : {"COMMIT" if options["commit"] else "DRY-RUN"}')
        log(f'{LOG_PREFIX} Audit dir  : {out_dir}')
        log('')

        ctx = RunContext(
            workbook_path=workbook,
            shop=shop,
            cutoff=cutoff,
            ar_cutoff=ar_cutoff,
            zig_rate=zig_rate,
            fuzzy_threshold=options['fuzzy_threshold'],
            commit=options['commit'],
            out_dir=out_dir,
            log=log,
            source_workbook=os.path.basename(workbook),
            cashier_user=cashier,
            fuzzy_matcher=FuzzyMatcher(threshold=options['fuzzy_threshold']),
        )

        # ──────────────────────────────────────────────────────────────────
        # Phase orchestration. Each phase is one atomic block; if --commit
        # is unset the whole thing rolls back at the end. The audit pack is
        # emitted unconditionally (file I/O is outside the transaction).
        # ──────────────────────────────────────────────────────────────────
        try:
            with transactional_run(commit=options['commit'], log=log):
                self._run_phase('products', products.run, ctx)
                self._run_phase('ar',       ar.run,       ctx)
                self._run_phase('layby',    layby.run,    ctx)
                self._run_phase('sales',    sales.run,    ctx)
                self._run_phase('cashbook', cashbook.run, ctx)

                # DB-derived audit CSVs MUST be queried inside the transaction
                # (otherwise dry-run rollback would have already wiped the data).
                log(f'{LOG_PREFIX} Emitting in-transaction audit CSVs…')
                audit.write_trial_balance(out_dir)
                audit.write_ar_aging(out_dir, as_of=cutoff)
                audit.write_shopstock(out_dir, ctx.qoh_meta)
        except ImportAborted as exc:
            log(f'{LOG_PREFIX} Import aborted: {exc}')
            ctx.errors.append(str(exc))
            self._emit_data_audit(ctx, out_dir, options['commit'], log)
            raise CommandError(str(exc)) from exc
        except DryRunRollback:
            # Expected during dry-run — handled by transactional_run.
            pass

        # ──────────────────────────────────────────────────────────────────
        # File-I/O audit CSVs — written from in-memory collectors, so these
        # survive rollback by design.
        # ──────────────────────────────────────────────────────────────────
        self._emit_data_audit(ctx, out_dir, options['commit'], log)

        log('')
        log(f'{LOG_PREFIX} Done. Reconciliation pack at: {out_dir}')
        if not options['commit']:
            log(f'{LOG_PREFIX} Reminder: this was a DRY-RUN — re-run with --commit to persist.')

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_logger(self):
        """Return a `log(msg)` callable that writes to stdout immediately."""
        def log(msg: str) -> None:
            self.stdout.write(msg)
            self.stdout.flush()
        return log

    def _run_phase(self, name: str, fn, ctx: RunContext) -> None:
        ctx.log(f'{LOG_PREFIX} ── Phase: {name} ─────────────────────────')
        fn(ctx)
        ctx.log('')

    def _assert_target_tables_empty(self) -> None:
        """Plan R4 — abort if target tables already have data.

        We check the canonical write-targets only. If the operator wants to
        re-run, they must `python manage.py flush --no-input` first.
        """
        non_empty = []
        for model in REQUIRED_EMPTY_MODELS:
            count = model.objects.count()
            if count:
                non_empty.append(f'{model.__name__}: {count}')
        if non_empty:
            raise CommandError(
                'Target tables are not empty (use --force to override):\n  '
                + '\n  '.join(non_empty)
            )

    def _emit_data_audit(self, ctx: RunContext, out_dir: Path,
                         commit: bool, log) -> None:
        """Write all the in-memory-collector-driven audit CSVs."""
        log(f'{LOG_PREFIX} Emitting data-derived audit CSVs…')
        audit.write_fuzzy_decisions(
            out_dir, ctx.fuzzy_matcher.decisions if ctx.fuzzy_matcher else [])
        audit.write_unmatched_sales(out_dir, ctx.unmatched_sales)
        audit.write_negative_qoh(out_dir, ctx.negative_qoh)
        audit.write_unmappable_expenses(out_dir, ctx.unmappable_expenses)
        audit.write_bad_debt_writeoffs(out_dir, ctx.bad_debt_writeoffs)
        audit.write_bad_debt_recoveries(out_dir, ctx.bad_debt_recoveries)
        audit.write_opening_ar_journal(out_dir, ctx.opening_ar_journal)
        audit.write_historical_archive_summary(out_dir, ctx.historical_counter)

        # Plan A polish: explicit stock-confidence + pricing + column-drift audits.
        audit.write_stock_opening_audit(out_dir, ctx.stock_opening_audit)
        audit.write_pricing_sanity(out_dir, ctx.pricing_sanity)
        audit.write_column_drift(out_dir, ctx.column_drift)

        # Decimal counts aren't JSON-serialisable in audit's text writer; cast.
        summary = {
            'workbook': os.path.basename(ctx.workbook_path),
            'shop_code': ctx.shop.code,
            'cutoff': ctx.cutoff.isoformat(),
            'ar_cutoff': ctx.ar_cutoff.isoformat(),
            'commit': commit,
            'counts': {k: str(v) for k, v in ctx.counts.items()},
            'errors': ctx.errors,
            'stock_confidence': self._stock_confidence_block(ctx),
        }
        audit.write_summary_text(out_dir, summary)

    def _stock_confidence_block(self, ctx: RunContext) -> dict:
        """Aggregate stock-tier counts for the operator summary."""
        from collections import Counter
        tier_counts = Counter(r['tier'] for r in ctx.stock_opening_audit)
        conf_counts = Counter(r['confidence'] for r in ctx.stock_opening_audit)
        return {
            'tiers': dict(tier_counts),
            'confidences': dict(conf_counts),
            'total_variants_estimated': len(ctx.stock_opening_audit),
            'pricing_flags': len(ctx.pricing_sanity),
            'column_drift_rows': len(ctx.column_drift),
        }
