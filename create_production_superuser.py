"""
Script to create a superuser for production Railway deployment.
Run this on Railway: railway run python create_production_superuser.py
"""

import os
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'inventorySystem.settings')
django.setup()

from django.contrib.auth import get_user_model

User = get_user_model()

def create_superuser():
    """Create a superuser with predefined credentials"""

    # Change these values as needed
    username = input("Enter username (default: admin): ").strip() or "admin"
    email = input("Enter email (optional): ").strip() or ""
    password = input("Enter password (minimum 8 characters): ").strip()

    if len(password) < 8:
        print("Error: Password must be at least 8 characters long.")
        return

    # Check if user already exists
    if User.objects.filter(username=username).exists():
        print(f"\nUser '{username}' already exists!")
        update = input("Do you want to update the password? [y/N]: ").strip().lower()

        if update == 'y':
            user = User.objects.get(username=username)
            user.set_password(password)
            user.is_superuser = True
            user.is_staff = True
            user.save()
            print(f"\n✓ Password updated for user '{username}'")
        else:
            print("No changes made.")
    else:
        # Create new superuser
        user = User.objects.create_superuser(
            username=username,
            email=email,
            password=password
        )
        print(f"\n✓ Superuser '{username}' created successfully!")

    print(f"\nLogin credentials:")
    print(f"  Username: {username}")
    print(f"  Password: {password}")
    print(f"\nYou can now login at: https://ims-production-45b3.up.railway.app/admin/")

if __name__ == "__main__":
    print("=" * 60)
    print("Production Superuser Creator for Railway")
    print("=" * 60)
    create_superuser()
