"""
Phase 3 — credit-clients sheet: import Customer records, opening AR invoices, and bad-debt write-off JEs.
"""
from datetime import date, timedelta
from decimal import Decimal

from accounting.models import ARInvoice, JournalEntry, JournalLine
from accounting.utils import MissingGLAccountError, require_gl
from inventory.importers.context import RunContext
from inventory.importers.excel_loader import load_credit_clients
from inventory.importers import historical as hist_writer
from inventory.importers.dry_run import update_dates
from inventory.importers.sales import _is_header_row
from inventory.models import Customer

LOG_PREFIX = '[IMPORT-EB]'
_SHEET_NAME = 'credit clients '   # workbook sheet has trailing space


def _next_ar_invoice_number(prefix: str) -> str:
    """Scan existing AR invoice numbers with `prefix` and return the next sequential one."""
    existing = ARInvoice.objects.filter(
        invoice_number__startswith=prefix
    ).values_list('invoice_number', flat=True)

    max_num = 0
    for inv_num in existing:
        try:
            num = int(inv_num[len(prefix):])
            max_num = max(max_num, num)
        except (ValueError, IndexError):
            pass
    return f'{prefix}{max_num + 1:04d}'


def _archive_invoice_rows(invoice_rows: list[dict], ctx: RunContext, customer_name: str) -> None:
    """Bulk-archive all raw invoice rows for a customer to HistoricalRecord."""
    records = [
        {
            'sheet_name':     _SHEET_NAME,
            'row_index':      row.get('row_index', 0),
            'row_data':       {'customer_name': customer_name, **row},
            'record_date':    row.get('date'),
            'shop':           ctx.shop,
            'source_workbook': ctx.source_workbook,
        }
        for row in invoice_rows
    ]
    hist_writer.bulk_archive(records, counter=ctx.historical_counter)


def _post_bad_debt_je(
    customer_name: str,
    amount: Decimal,
    ar_account,
    bad_debt_account,
    ctx: RunContext,
    as_of_date: date | None,
) -> JournalEntry:
    """Post Dr Bad Debt Expense / Cr AR and return the balanced JournalEntry."""
    je = JournalEntry.objects.create(
        memo=f'Bad debt write-off — {customer_name}',
        shop=ctx.shop,
    )
    if as_of_date is not None:
        update_dates(JournalEntry, je.pk, entry_date=as_of_date)

    JournalLine.objects.create(
        entry=je,
        account=bad_debt_account,
        debit=amount,
        description=f'Bad debt: {customer_name}',
    )
    JournalLine.objects.create(
        entry=je,
        account=ar_account,
        credit=amount,
        description=f'Write off A/R: {customer_name}',
    )
    je.assert_balanced()
    return je


def _post_opening_ar_je(
    customer: Customer,
    amount: Decimal,
    ar_account,
    retained_earnings_account,
    ctx: RunContext,
    as_of_date: date | None,
) -> JournalEntry:
    """Post Dr AR / Cr Retained Earnings and return the balanced JournalEntry."""
    je = JournalEntry.objects.create(
        memo=f'Opening AR — {customer.name}',
        shop=ctx.shop,
    )
    if as_of_date is not None:
        update_dates(JournalEntry, je.pk, entry_date=as_of_date)

    JournalLine.objects.create(
        entry=je,
        account=ar_account,
        debit=amount,
        description=f'Opening AR balance: {customer.name}',
        customer=customer,
    )
    JournalLine.objects.create(
        entry=je,
        account=retained_earnings_account,
        credit=amount,
        description=f'Opening equity offset: {customer.name}',
    )
    je.assert_balanced()
    return je


def _create_opening_ar_invoice(
    customer: Customer,
    amount: Decimal,
    invoice_date: date,
    ctx: RunContext,
) -> ARInvoice:
    """Create a single PENDING ARInvoice representing the customer's opening balance."""
    year = invoice_date.year
    prefix = f'AR-OPEN-{year}-'
    invoice_number = _next_ar_invoice_number(prefix)

    invoice = ARInvoice.objects.create(
        customer=customer,
        invoice_number=invoice_number,
        invoice_date=invoice_date,
        due_date=invoice_date + timedelta(days=30),
        total_amount=amount,
        amount_paid=Decimal('0'),
        status='PENDING',
        shop=ctx.shop,
    )
    # Backdate created_date to match the invoice date (plan R1 — auto_now_add bypass)
    update_dates(ARInvoice, invoice.pk, created_date=invoice_date)
    return invoice


def run(ctx: RunContext) -> None:
    """Import credit-clients sheet: live customers + opening AR, or bad-debt write-offs."""

    # Verify required GL accounts before any DB writes
    ar_account              = require_gl('1200')
    retained_earnings_acct  = require_gl('3100')
    bad_debt_account        = require_gl('6500')

    entries = load_credit_clients(ctx.workbook_path)

    live_count      = 0
    bad_debt_count  = 0

    header_skipped = 0
    for entry in entries:
        name        = entry['customer_name']
        balance     = entry['outstanding_balance']
        earliest    = entry['earliest_invoice_date']
        inv_rows    = entry.get('invoice_rows', [])

        # ── Path Z: header / subtotal row — archive, never become a Customer.
        # Catches 'TOTAL BAD DEBTS', 'TOTAL CREDIT BALANCE', 'JAN 2026 BAL B/D',
        # 'may 2025 bal bd', 'jan 2026. opening bal', etc.
        if _is_header_row(name):
            _archive_invoice_rows(inv_rows, ctx, name)
            header_skipped += 1
            continue

        # ── Path A: zero / nil balance — archive and skip ────────────────────
        if balance is None or balance <= Decimal('0'):
            _archive_invoice_rows(inv_rows, ctx, name)
            continue

        # ── Path B: pre-cutoff (bad debt) ─────────────────────────────────────
        if earliest is None or earliest < ctx.ar_cutoff:
            _archive_invoice_rows(inv_rows, ctx, name)

            je = _post_bad_debt_je(
                customer_name=name,
                amount=balance,
                ar_account=ar_account,
                bad_debt_account=bad_debt_account,
                ctx=ctx,
                as_of_date=earliest,
            )

            ctx.bad_debt_writeoffs.append({
                'customer_id':             '',
                'customer_name':           name,
                'original_invoice_date':   earliest,
                'original_amount':         balance,
                'writeoff_je_id':          je.id,
            })
            ctx.counts['bad_debt_customers'] = ctx.counts.get('bad_debt_customers', 0) + 1
            ctx.counts['bad_debt_amount_total'] = (
                ctx.counts.get('bad_debt_amount_total', Decimal('0')) + balance
            )
            bad_debt_count += 1
            continue

        # ── Path C: live customer (invoice date >= ar_cutoff) ─────────────────
        cust = Customer.objects.create(
            name=name,
            status='ACTIVE',
            credit_limit=Decimal('500'),
            current_balance=balance,
        )

        invoice = _create_opening_ar_invoice(
            customer=cust,
            amount=balance,
            invoice_date=earliest,
            ctx=ctx,
        )

        je = _post_opening_ar_je(
            customer=cust,
            amount=balance,
            ar_account=ar_account,
            retained_earnings_account=retained_earnings_acct,
            ctx=ctx,
            as_of_date=earliest,
        )

        _archive_invoice_rows(inv_rows, ctx, name)

        ctx.opening_ar_journal.append({
            'customer_id':              cust.id,
            'customer_name':            name,
            'je_id':                    je.id,
            'je_date':                  earliest,
            'total_amount':             balance,
            'ar_account':               '1200',
            'retained_earnings_account': '3100',
        })
        ctx.counts['ar_customers_live'] = ctx.counts.get('ar_customers_live', 0) + 1
        live_count += 1

    ctx.log(
        f'{LOG_PREFIX} ar: {live_count} live customer(s), '
        f'{bad_debt_count} bad-debt write-off(s), '
        f'{header_skipped} header rows skipped'
    )
