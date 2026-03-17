"""
Management command to backfill opening inventory balance to GL.

This creates a journal entry to record the current on-hand inventory value
as an opening balance: Dr Inventory (1300) / Cr Opening Balance Equity (3900)

Usage:
    python manage.py backfill_inventory_opening_balance [--dry-run]
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Sum, F
from decimal import Decimal
from accounting.models import GLAccount, JournalEntry, JournalLine
from inventory.models import Inventory


class Command(BaseCommand):
    help = 'Backfill opening inventory balance to General Ledger'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be posted without actually creating entries',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']

        # Calculate current inventory value
        inventory_value = Inventory.objects.aggregate(
            total=Sum(F('quantity_in_Stock') * F('purchase_price'))
        )['total'] or Decimal('0')

        if inventory_value <= 0:
            self.stdout.write(
                self.style.WARNING('No inventory value found. Nothing to backfill.')
            )
            return

        self.stdout.write(f"\nCurrent physical inventory value: ${inventory_value:,.2f}")

        # Get GL account balances
        try:
            inventory_account = GLAccount.objects.get(code='1300')
            current_gl_balance = inventory_account.balance
            self.stdout.write(f"Current GL Account 1300 balance: ${current_gl_balance:,.2f}")
        except GLAccount.DoesNotExist:
            self.stdout.write(
                self.style.ERROR('GL Account 1300 (Inventory) not found. Run init_gl_accounts first.')
            )
            return

        # Calculate adjustment needed
        adjustment = inventory_value - current_gl_balance

        if adjustment <= 0:
            self.stdout.write(
                self.style.SUCCESS(
                    f'\nNo adjustment needed. GL balance matches or exceeds inventory value.'
                )
            )
            return

        self.stdout.write(
            self.style.WARNING(f"\nAdjustment needed: ${adjustment:,.2f}")
        )

        if dry_run:
            self.stdout.write(
                self.style.NOTICE('\n[DRY RUN] Would create the following journal entry:')
            )
            self.stdout.write(f"  Dr Inventory (1300): ${adjustment:,.2f}")
            self.stdout.write(f"  Cr Opening Balance Equity (3900): ${adjustment:,.2f}")
            return

        # Check for Opening Balance Equity account
        try:
            equity_account = GLAccount.objects.get(code='3900')
        except GLAccount.DoesNotExist:
            self.stdout.write(
                self.style.WARNING(
                    '\nGL Account 3900 (Opening Balance Equity) not found. Creating it...'
                )
            )
            equity_account = GLAccount.objects.create(
                code='3900',
                name='Opening Balance Equity',
                type='EQUITY'
            )
            self.stdout.write(self.style.SUCCESS('Created account 3900'))

        # Create journal entry
        with transaction.atomic():
            je = JournalEntry.objects.create(
                memo='Opening balance - inventory on hand',
                reference='OPENING-INV',
                created_by=None
            )

            # Dr Inventory
            JournalLine.objects.create(
                entry=je,
                account=inventory_account,
                debit=adjustment,
                description='Opening inventory balance'
            )

            # Cr Opening Balance Equity
            JournalLine.objects.create(
                entry=je,
                account=equity_account,
                credit=adjustment,
                description='Opening inventory balance'
            )

            self.stdout.write(
                self.style.SUCCESS(
                    f'\nCreated journal entry #{je.id}'
                )
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f'Posted ${adjustment:,.2f} to Inventory account'
                )
            )

        # Verify new balance
        inventory_account.refresh_from_db()
        self.stdout.write(
            self.style.SUCCESS(
                f'New GL Account 1300 balance: ${inventory_account.balance:,.2f}'
            )
        )

        if abs(inventory_account.balance - inventory_value) < Decimal('0.01'):
            self.stdout.write(
                self.style.SUCCESS(
                    '\nGL balance now matches physical inventory value!'
                )
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    f'\nSmall difference remains: ${abs(inventory_account.balance - inventory_value):,.2f}'
                )
            )
