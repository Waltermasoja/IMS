from django.core.management.base import BaseCommand
from inventory.models import Shop


class Command(BaseCommand):
    help = "Seed the two initial shops (baby bazaar + clothing). Idempotent."

    SHOPS = [
        {
            'code': 'BBY',
            'name': 'Baby Bazaar',
            'address': '',
            'phone': '',
        },
        {
            'code': 'CLO',
            'name': 'Clothing Shop',
            'address': '',
            'phone': '',
        },
    ]

    def handle(self, *args, **options):
        created, updated = 0, 0
        for spec in self.SHOPS:
            shop, was_created = Shop.objects.get_or_create(
                code=spec['code'],
                defaults={
                    'name': spec['name'],
                    'address': spec['address'],
                    'phone': spec['phone'],
                    'is_active': True,
                },
            )
            if was_created:
                created += 1
                self.stdout.write(self.style.SUCCESS(f"Created shop: {shop.code} — {shop.name}"))
            else:
                updated += 1
                self.stdout.write(f"Shop already exists: {shop.code} — {shop.name}")
        self.stdout.write(self.style.SUCCESS(
            f"Done. Created {created}, already-existing {updated}. Total shops: {Shop.objects.count()}."
        ))
