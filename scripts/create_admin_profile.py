"""
Create UserProfile for admin user on Railway
Run: railway run python scripts/create_admin_profile.py
"""

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
os.chdir(_ROOT)

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'inventorySystem.settings')
django.setup()

from django.contrib.auth import get_user_model
from inventory.models import UserProfile

User = get_user_model()

print("=" * 60)
print("Creating/Updating Admin User Profile")
print("=" * 60)

username = "admin"

try:
    user = User.objects.get(username=username)
    print(f"\n✓ Found user: {username}")

    # Check if profile exists
    try:
        profile = user.profile
        print(f"✓ UserProfile already exists")
        print(f"  - Role: {profile.role}")
        print(f"  - Can make sales: {profile.can_make_sales}")
        print(f"  - Can manage inventory: {profile.can_manage_inventory}")

        # Update to admin role with full permissions
        profile.role = 'admin'
        profile.can_make_sales = True
        profile.can_process_returns = True
        profile.can_apply_discounts = True
        profile.max_discount_percent = 100.00
        profile.can_view_reports = True
        profile.can_manage_inventory = True
        profile.can_manage_suppliers = True
        profile.can_manage_customers = True
        profile.can_manage_users = True
        profile.save()

        print(f"\n✓ Profile updated to admin with full permissions")

    except UserProfile.DoesNotExist:
        print(f"✗ UserProfile does NOT exist - creating now...")

        # Create profile with admin permissions
        profile = UserProfile.objects.create(
            user=user,
            role='admin',
            can_make_sales=True,
            can_process_returns=True,
            can_apply_discounts=True,
            max_discount_percent=100.00,
            can_view_reports=True,
            can_manage_inventory=True,
            can_manage_suppliers=True,
            can_manage_customers=True,
            can_manage_users=True
        )

        print(f"✓ UserProfile created successfully!")

    print(f"\n" + "=" * 60)
    print(f"ADMIN USER READY:")
    print(f"  Username: {username}")
    print(f"  Password: Admin@IMS2024!")
    print(f"  Role: {profile.role}")
    print(f"  Is superuser: {user.is_superuser}")
    print(f"  Is staff: {user.is_staff}")
    print(f"\nLogin at:")
    print(f"  Admin: https://ims-production-45b3.up.railway.app/admin/")
    print(f"  IMS:   https://ims-production-45b3.up.railway.app/login/")
    print(f"=" * 60)

except User.DoesNotExist:
    print(f"\n✗ User '{username}' not found!")
    print("Run this first: railway run python scripts/verify_and_fix_admin.py")

except Exception as e:
    print(f"\n✗ Error: {e}")
    import traceback
    traceback.print_exc()
