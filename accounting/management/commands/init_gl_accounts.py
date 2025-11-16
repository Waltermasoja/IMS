"""
Management command to initialize GL (General Ledger) accounts for the accounting system.
Usage: python manage.py init_gl_accounts
"""
from django.core.management.base import BaseCommand
from accounting.models import GLAccount


class Command(BaseCommand):
    help = 'Initialize GL accounts for the accounting system'

    def handle(self, *args, **options):
        accounts = [
            # Assets
            {'code': '1000', 'name': 'Cash', 'type': 'ASSET'},
            {'code': '1200', 'name': 'Accounts Receivable', 'type': 'ASSET'},
            {'code': '1300', 'name': 'Inventory', 'type': 'ASSET'},
            {'code': '1400', 'name': 'Prepaid Expenses', 'type': 'ASSET'},
            {'code': '1500', 'name': 'Fixed Assets', 'type': 'ASSET'},
            
            # Liabilities
            {'code': '2000', 'name': 'Accounts Payable', 'type': 'LIAB'},
            {'code': '2100', 'name': 'Short-term Debt', 'type': 'LIAB'},
            {'code': '2300', 'name': 'Unearned Revenue', 'type': 'LIAB'},
            
            # Equity
            {'code': '3000', 'name': 'Owner\'s Equity', 'type': 'EQUITY'},
            {'code': '3100', 'name': 'Retained Earnings', 'type': 'EQUITY'},
            
            # Income
            {'code': '4000', 'name': 'Sales Revenue', 'type': 'INCOME'},
            {'code': '4800', 'name': 'Other Income', 'type': 'INCOME'},
            
            # Expenses
            {'code': '5000', 'name': 'Cost of Goods Sold (COGS)', 'type': 'EXP'},
            {'code': '6000', 'name': 'Rent Expense', 'type': 'EXP'},
            {'code': '6100', 'name': 'Utilities Expense', 'type': 'EXP'},
            {'code': '6200', 'name': 'Wages Expense', 'type': 'EXP'},
            {'code': '6300', 'name': 'Freight Expense', 'type': 'EXP'},
            {'code': '6400', 'name': 'Marketing Expense', 'type': 'EXP'},
            {'code': '6900', 'name': 'Other Expenses', 'type': 'EXP'},
        ]
        
        created_count = 0
        skipped_count = 0
        
        for acc_data in accounts:
            account, created = GLAccount.objects.get_or_create(
                code=acc_data['code'],
                defaults={
                    'name': acc_data['name'],
                    'type': acc_data['type'],
                    'is_active': True
                }
            )
            
            if created:
                self.stdout.write(
                    self.style.SUCCESS(f'✓ Created: {acc_data["code"]} - {acc_data["name"]}')
                )
                created_count += 1
            else:
                self.stdout.write(
                    self.style.WARNING(f'⊗ Exists:  {acc_data["code"]} - {acc_data["name"]}')
                )
                skipped_count += 1
        
        self.stdout.write('\n')
        self.stdout.write(self.style.SUCCESS(f'Summary: {created_count} created, {skipped_count} already existed'))
        self.stdout.write(self.style.SUCCESS('GL accounts initialization complete!'))
