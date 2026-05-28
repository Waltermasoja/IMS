"""
Idempotently create the `imported_history` placeholder user.

This user is used as `SalesTicket.cashier` (and similar non-null FKs) for
records produced by the ExoticBlossom Excel importer where the original
cashier is unknown. The account is created inactive — it can never log in.

Usage:
    python manage.py seed_imported_history_user
"""
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand


PLACEHOLDER_USERNAME = 'imported_history'


class Command(BaseCommand):
    help = 'Create the imported_history placeholder user used by the Excel importer.'

    def handle(self, *args, **options):
        user, created = User.objects.get_or_create(
            username=PLACEHOLDER_USERNAME,
            defaults={
                'first_name': 'Imported',
                'last_name': 'History',
                'is_active': False,   # cannot log in
                'is_staff': False,
                'is_superuser': False,
            },
        )
        if created:
            user.set_unusable_password()
            user.save(update_fields=['password'])
            self.stdout.write(self.style.SUCCESS(
                f'[+] Created placeholder user "{PLACEHOLDER_USERNAME}" (id={user.id}).'
            ))
        else:
            self.stdout.write(self.style.WARNING(
                f'[~] Placeholder user "{PLACEHOLDER_USERNAME}" already exists (id={user.id}).'
            ))
