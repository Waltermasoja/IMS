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
            # Assets — tender-side accounts align with SalesTicket.tender_type
            {'code': '1000', 'name': 'Cash on Hand', 'type': 'ASSET'},
            {'code': '1010', 'name': 'EcoCash Float', 'type': 'ASSET'},
            {'code': '1020', 'name': 'Bank Current Account', 'type': 'ASSET'},
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
            {'code': '4100', 'name': 'Sales Discounts', 'type': 'CONTRA_REV'},
            {'code': '4800', 'name': 'Other Income', 'type': 'INCOME'},

            # Expenses
            {'code': '5000', 'name': 'Cost of Goods Sold (COGS)', 'type': 'EXP'},
            {'code': '5100', 'name': 'Inventory Loss (Damage/Shrinkage)', 'type': 'EXP'},
            {'code': '6000', 'name': 'Rent Expense', 'type': 'EXP'},
            {'code': '6100', 'name': 'Utilities Expense', 'type': 'EXP'},
            {'code': '6200', 'name': 'Wages Expense', 'type': 'EXP'},
            {'code': '6300', 'name': 'Freight Expense', 'type': 'EXP'},
            {'code': '6400', 'name': 'Marketing Expense', 'type': 'EXP'},
            {'code': '6900', 'name': 'Other Expenses', 'type': 'EXP'},
        ]

        created_count = 0
        updated_count = 0
        unchanged_count = 0

        for acc_data in accounts:
            account, created = GLAccount.objects.get_or_create(
                code=acc_data['code'],
                defaults={
                    'name': acc_data['name'],
                    'type': acc_data['type'],
                    'is_active': True,
                },
            )

            if created:
                self.stdout.write(self.style.SUCCESS(
                    f'[+] Created: {acc_data["code"]} - {acc_data["name"]}'
                ))
                created_count += 1
                continue

            # Existing account — update name/type if they drifted
            changed = False
            if account.name != acc_data['name']:
                self.stdout.write(self.style.WARNING(
                    f'[~] Renamed: {acc_data["code"]} "{account.name}" -> "{acc_data["name"]}"'
                ))
                account.name = acc_data['name']
                changed = True
            if account.type != acc_data['type']:
                account.type = acc_data['type']
                changed = True
            if changed:
                account.save(update_fields=['name', 'type'])
                updated_count += 1
            else:
                unchanged_count += 1

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'Summary: {created_count} created, {updated_count} updated, {unchanged_count} unchanged'
        ))
        self.stdout.write(self.style.SUCCESS('GL accounts initialization complete!'))
