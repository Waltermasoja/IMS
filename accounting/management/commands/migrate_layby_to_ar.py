"""
Management command to migrate existing layby plans to create AR invoices.
Run this after adding the ar_invoice field to LaybyPlan model.
"""
from django.core.management.base import BaseCommand
from accounting.models import LaybyPlan
from accounting.utils import create_layby_ar_invoice


class Command(BaseCommand):
    help = 'Create AR invoices for existing layby plans that do not have them'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be created without actually creating invoices',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']

        # Find all layby plans without AR invoices
        plans_without_invoice = LaybyPlan.objects.filter(ar_invoice__isnull=True)
        total_plans = plans_without_invoice.count()

        if total_plans == 0:
            self.stdout.write(self.style.SUCCESS('All layby plans already have AR invoices!'))
            return

        self.stdout.write(f'Found {total_plans} layby plans without AR invoices.')

        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN MODE - No changes will be made'))
            for plan in plans_without_invoice:
                self.stdout.write(
                    f'  - Plan #{plan.id}: {plan.customer.name} - ${plan.total_price} '
                    f'(Status: {plan.status}, Paid: ${plan.amount_paid})'
                )
            return

        # Create AR invoices for each plan
        created_count = 0
        error_count = 0

        for plan in plans_without_invoice:
            try:
                invoice = create_layby_ar_invoice(plan)
                created_count += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f'[OK] Created invoice {invoice.invoice_number} for Plan #{plan.id} - '
                        f'{plan.customer.name} (${plan.total_price})'
                    )
                )
            except Exception as e:
                error_count += 1
                self.stdout.write(
                    self.style.ERROR(
                        f'[ERROR] Error creating invoice for Plan #{plan.id}: {str(e)}'
                    )
                )

        # Summary
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(f'Migration complete!'))
        self.stdout.write(f'  - AR Invoices created: {created_count}')
        if error_count > 0:
            self.stdout.write(self.style.WARNING(f'  - Errors: {error_count}'))
        self.stdout.write('')
        self.stdout.write('Note: Customer balances have been updated to reflect layby AR.')
