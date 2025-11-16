# Railway Production Superuser Setup Guide

## The Problem

When you run `python manage.py createsuperuser` locally, it creates the user in your **local SQLite database**, NOT in the Railway production database.

## Solutions (Choose One)

### Method 1: Using the Management Command (Recommended)

This is the easiest and most secure method.

**Step 1: Push your code to Railway**
```powershell
git add .
git commit -m "Add superuser creation command"
git push
```

**Step 2: Run the command on Railway**
```powershell
# Replace with your actual password
railway run python manage.py create_admin --username admin --password YourSecurePassword123
```

**Step 3: Login**
Visit: https://ims-production-45b3.up.railway.app/admin/
- Username: `admin`
- Password: `YourSecurePassword123`

---

### Method 2: Using the Python Script (Interactive)

**Step 1: Push the script to Railway**
```powershell
git add create_production_superuser.py
git commit -m "Add production superuser script"
git push
```

**Step 2: Run the script on Railway**
```powershell
railway run python create_production_superuser.py
```

**Step 3: Follow the prompts**
- Enter username (or press Enter for "admin")
- Enter email (optional)
- Enter password (minimum 8 characters)

---

### Method 3: Using Railway Shell (Advanced)

**Step 1: Open Railway shell**
```powershell
railway run bash
```

**Step 2: Inside the shell, run Django shell**
```bash
python manage.py shell
```

**Step 3: Create superuser programmatically**
```python
from django.contrib.auth import get_user_model
User = get_user_model()

# Create or update user
username = "admin"
password = "YourSecurePassword123"

if User.objects.filter(username=username).exists():
    user = User.objects.get(username=username)
    user.set_password(password)
else:
    user = User.objects.create_superuser(username=username, password=password)

user.is_superuser = True
user.is_staff = True
user.save()

print(f"✓ Superuser '{username}' ready!")
exit()
```

**Step 4: Exit shell**
```bash
exit
```

---

## Best Practices

### Strong Password Requirements
- Minimum 8 characters
- Mix of letters, numbers, and symbols
- Example: `Admin@IMS2024!`

### Environment Variables (Future Enhancement)

For better security, you can use environment variables:

**On Railway Dashboard:**
1. Go to your project
2. Click "Variables"
3. Add:
   - `DJANGO_SUPERUSER_USERNAME` = `admin`
   - `DJANGO_SUPERUSER_PASSWORD` = `YourSecurePassword123`

**Update the command to use env vars:**
```python
import os
username = os.getenv('DJANGO_SUPERUSER_USERNAME', 'admin')
password = os.getenv('DJANGO_SUPERUSER_PASSWORD')
```

---

## Troubleshooting

### Issue: "User already exists"
**Solution:** Use the management command with the same username to update the password:
```powershell
railway run python manage.py create_admin --username admin --password NewPassword123
```

### Issue: "Password too common"
**Solution:** Use a stronger password with:
- At least 8 characters
- Mix of uppercase and lowercase
- Numbers and special characters

### Issue: "Railway command not found"
**Solution:** Install Railway CLI:
```powershell
npm install -g @railway/cli
railway login
railway link
```

---

## Security Notes

1. **Never commit passwords to Git** - Always use environment variables for production
2. **Change default passwords** - Don't use "admin/admin" in production
3. **Enable 2FA** - Consider adding django-two-factor-auth for extra security
4. **Limit superuser accounts** - Only create what you need

---

## Quick Reference

```powershell
# Create new superuser on Railway
railway run python manage.py create_admin --username admin --password YourPassword123

# Update existing superuser password
railway run python manage.py create_admin --username admin --password NewPassword123

# Check Railway logs
railway logs

# Open Railway shell
railway run bash
```
