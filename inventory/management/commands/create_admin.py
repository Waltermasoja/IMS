"""
Django management command to create or update a superuser non-interactively.
Usage: python manage.py create_admin --username admin --password YourPassword123
"""

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

User = get_user_model()


class Command(BaseCommand):
    help = 'Create or update a superuser for production deployment'

    def add_arguments(self, parser):
        parser.add_argument('--username', type=str, default='admin', help='Username for superuser')
        parser.add_argument('--email', type=str, default='', help='Email for superuser')
        parser.add_argument('--password', type=str, required=True, help='Password for superuser')

    def handle(self, *args, **options):
        username = options['username']
        email = options['email']
        password = options['password']

        if len(password) < 8:
            self.stdout.write(self.style.ERROR('Password must be at least 8 characters long.'))
            return

        # Check if user exists
        if User.objects.filter(username=username).exists():
            user = User.objects.get(username=username)
            user.set_password(password)
            user.is_superuser = True
            user.is_staff = True
            user.email = email if email else user.email
            user.save()

            self.stdout.write(self.style.SUCCESS(f'✓ Superuser "{username}" updated successfully!'))
            self.stdout.write(self.style.WARNING(f'  Password has been reset.'))
        else:
            # Create new superuser
            user = User.objects.create_superuser(
                username=username,
                email=email,
                password=password
            )

            self.stdout.write(self.style.SUCCESS(f'✓ Superuser "{username}" created successfully!'))

        self.stdout.write('')
        self.stdout.write(self.style.HTTP_INFO('Login credentials:'))
        self.stdout.write(f'  Username: {username}')
        self.stdout.write(f'  Password: {password}')
        self.stdout.write('')
        self.stdout.write('You can now login at the admin panel.')
