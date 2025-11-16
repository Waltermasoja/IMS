"""
Verify and fix admin user on Railway production
Run: railway run python verify_and_fix_admin.py
"""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'inventorySystem.settings')
django.setup()

from django.contrib.auth import get_user_model

User = get_user_model()

print("=" * 60)
print("Admin User Verification and Fix")
print("=" * 60)

username = "admin"
new_password = "Admin@IMS2024!"

try:
    # Try to get the user
    user = User.objects.get(username=username)

    print(f"\n✓ User '{username}' found in database")
    print(f"  - Email: {user.email or '(not set)'}")
    print(f"  - Is superuser: {user.is_superuser}")
    print(f"  - Is staff: {user.is_staff}")
    print(f"  - Is active: {user.is_active}")
    print(f"  - Date joined: {user.date_joined}")
    print(f"  - Last login: {user.last_login or 'Never'}")

    # Fix the user
    print(f"\nResetting password and fixing permissions...")
    user.set_password(new_password)
    user.is_superuser = True
    user.is_staff = True
    user.is_active = True
    user.save()

    print(f"\n✓ User updated successfully!")

    # Verify password works
    from django.contrib.auth import authenticate
    test_user = authenticate(username=username, password=new_password)

    if test_user is not None:
        print(f"✓ Password verification PASSED - login should work!")
    else:
        print(f"✗ Password verification FAILED - something is wrong")

    print(f"\n" + "=" * 60)
    print(f"LOGIN CREDENTIALS:")
    print(f"  URL: https://ims-production-45b3.up.railway.app/admin/")
    print(f"  Username: {username}")
    print(f"  Password: {new_password}")
    print(f"=" * 60)

except User.DoesNotExist:
    print(f"\n✗ User '{username}' NOT found in database!")
    print(f"\nCreating new superuser...")

    user = User.objects.create_superuser(
        username=username,
        password=new_password,
        email=""
    )

    print(f"✓ Superuser created successfully!")
    print(f"\nLOGIN CREDENTIALS:")
    print(f"  URL: https://ims-production-45b3.up.railway.app/admin/")
    print(f"  Username: {username}")
    print(f"  Password: {new_password}")

except Exception as e:
    print(f"\n✗ Error: {e}")
    import traceback
    traceback.print_exc()
