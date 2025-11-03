from django.core.management.base import BaseCommand
from inventory.models import GLAccount

ACCOUNTS = [
    ('1000', 'Cash', 'ASSET'),
    ('1200', 'Accounts Receivable', 'ASSET'),
    ('1500', 'Inventory', 'ASSET'),
    ('2300', 'Unearned Revenue - Layby', 'LIAB'),
    ('4000', 'Sales Revenue', 'INCOME'),
    ('4800', 'Other Income - Layby Forfeit', 'INCOME'),
    ('5000', 'Cost of Goods Sold', 'EXP'),
]

class Command(BaseCommand):
    help = 'Seed basic chart of accounts for POS/Layby/AR'

    def handle(self, *args, **options):
        created = 0
        for code, name, typ in ACCOUNTS:
            obj, was_created = GLAccount.objects.get_or_create(code=code, defaults={'name': name, 'type': typ})
            if not was_created:
                # ensure name/type up to date
                if obj.name != name or obj.type != typ:
                    obj.name = name
                    obj.type = typ
                    obj.save()
            else:
                created += 1
        self.stdout.write(self.style.SUCCESS(f'Seeded GL accounts. New created: {created}'))
