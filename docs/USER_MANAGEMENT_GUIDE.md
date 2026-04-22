# User Management System Guide

## Overview

The Inventory Management System now includes a comprehensive visual user management interface designed for non-technical users. This replaces the need to use the Django admin panel for user management tasks.

## Accessing User Management

**Requirements:**
- You must be logged in as an **Administrator** or **Superuser**
- Navigate to: **Administration → User Management** (in the sidebar)
- Direct URL: `http://127.0.0.1:8000/user-management/`

## Features

### 1. User Management Dashboard

The main dashboard provides:
- **User Statistics**: Total users, active users, administrators, and sales staff
- **User List**: Complete list of all system users with key information
- **Quick Actions**: Create users, view role templates, manage permissions

#### User List Columns:
- **User**: Avatar, username, and email
- **Role**: User's assigned role (Admin, Manager, Sales, Viewer)
- **Status**: Active or Inactive indicator
- **Sales**: Total sales count and revenue generated
- **Permissions**: Visual icons showing granted permissions
- **Joined Date**: When the user account was created
- **Actions**: View, Edit, and Delete buttons

### 2. Creating a New User

**Path**: User Management → Add New User

**Steps**:
1. Click **"Add New User"** button
2. Fill in required information:
   - **Username** (required, unique)
   - **Email** (optional but recommended)
   - **First Name** & **Last Name** (optional)
   - **Password** (required, must match confirmation)

3. Select **Role & Status**:
   - Choose role: Administrator, Manager, Sales Associate, or Viewer
   - Toggle **Active Account** (user can log in)
   - Toggle **Staff Status** (access Django admin if needed)

4. Configure **POS & Sales Permissions**:
   - ✓ Make Sales - Process sales transactions
   - ✓ Process Returns - Handle product returns
   - ✓ Apply Discounts - Give discounts on sales
   - Set **Maximum Discount %** (default: 10%)

5. Configure **System Permissions**:
   - ✓ View Reports - Access sales and inventory reports
   - ✓ Manage Inventory - Add, edit, delete products
   - ✓ Manage Suppliers - Add and edit supplier information
   - ✓ Manage Users - Create/edit users (admin only)

6. Click **"Create User"**

### 3. Editing an Existing User

**Path**: User Management → Click user's "Edit" icon

**What You Can Edit**:
- Email, first name, last name
- Password (leave blank to keep current)
- Role and account status
- All permissions and discount limits

**Important Notes**:
- Username **cannot be changed** after creation
- You **cannot edit your own account** to prevent lockout
- Non-superusers **cannot edit superuser accounts**

### 4. Viewing User Details

**Path**: User Management → Click user's "Eye" icon

**Information Shown**:
- User status (Active/Inactive, Staff, Superuser)
- Assigned role and description
- Account creation date
- **Sales Performance**:
  - Total sales count and revenue
  - Sales this month and monthly revenue
- **All Permissions**: Visual breakdown of granted permissions
- **Recent Sales**: Last 10 sales made by this user

### 5. Deactivating or Deleting Users

**Path**: User Management → Click user's "Delete" icon

**Two Options**:
1. **Deactivate**: User cannot log in but data is preserved
   - Recommended for temporary suspension
   - Can be reactivated later

2. **Delete**: Permanently removes user account
   - Use with caution
   - Sales records remain in system (linked to username)

**Safety Features**:
- Cannot delete your own account
- Non-superusers cannot delete superuser accounts
- Confirmation modal prevents accidental deletion

### 6. Role Templates

**Path**: User Management → Role Templates

View pre-configured permission sets for each role:

#### **Administrator**
- Full system access
- Can manage users and system settings
- All permissions enabled
- Best for: Business owners, IT admins, system managers

#### **Manager**
- Operational control
- Can manage inventory, sales, and suppliers
- Can view all reports
- Cannot manage users
- Best for: Store managers, operations supervisors, department heads

#### **Sales Associate**
- POS operations only
- Can make sales, process returns, apply discounts
- Cannot view reports or manage inventory
- Best for: Cashiers, sales associates, customer service reps

#### **Viewer**
- Read-only access
- Can only view reports
- No operational permissions
- Best for: Accountants, auditors, external consultants

### 7. Permission Comparison Matrix

The role templates page includes a comprehensive matrix showing which permissions each role has by default.

## User Roles Explained

### Administrator
**Description**: Full administrative access including user management and system settings

**Default Permissions**:
- ✓ Make Sales
- ✓ Process Returns
- ✓ Apply Discounts (unlimited)
- ✓ View Reports
- ✓ Manage Inventory
- ✓ Manage Suppliers
- ✓ Manage Users

**Access Level**: Everything in the system

### Manager
**Description**: Operational management with inventory and sales control

**Default Permissions**:
- ✓ Make Sales
- ✓ Process Returns
- ✓ Apply Discounts (up to set limit)
- ✓ View Reports
- ✓ Manage Inventory
- ✓ Manage Suppliers
- ✗ Manage Users

**Access Level**: All operational features except user management

### Sales Associate
**Description**: Point of sale operations and customer service

**Default Permissions**:
- ✓ Make Sales
- ✓ Process Returns
- ✓ Apply Discounts (limited)
- ✗ View Reports
- ✗ Manage Inventory
- ✗ Manage Suppliers
- ✗ Manage Users

**Access Level**: POS interface, customer management, layby plans

### Viewer
**Description**: Read-only access to reports and inventory

**Default Permissions**:
- ✗ Make Sales
- ✗ Process Returns
- ✗ Apply Discounts
- ✓ View Reports
- ✗ Manage Inventory
- ✗ Manage Suppliers
- ✗ Manage Users

**Access Level**: Reports and read-only data access

## Best Practices

### Security
1. **Use Strong Passwords**: Require at least 8 characters with mixed case, numbers
2. **Principle of Least Privilege**: Give users only the permissions they need
3. **Regular Audits**: Review user list monthly and deactivate unused accounts
4. **Role-Based Assignment**: Use standard roles instead of custom permissions when possible

### User Management
1. **Naming Convention**: Use consistent username format (e.g., firstname.lastname)
2. **Email Addresses**: Always add email for password reset capability
3. **Onboarding**: Create accounts before employee start date
4. **Offboarding**: Deactivate accounts immediately when employee leaves

### Discount Limits
- **Sales Associates**: 5-10% maximum
- **Managers**: 15-20% maximum
- **Administrators**: Unlimited (use with caution)

### Monitoring
1. Check **Sales Performance** on user detail pages regularly
2. Review low-performing accounts monthly
3. Investigate unusual discount usage patterns
4. Monitor after-hours sales activity

## Common Tasks

### Adding a New Cashier
1. Go to User Management
2. Click "Add New User"
3. Set role to "Sales Associate"
4. Enable: Make Sales, Process Returns, Apply Discounts
5. Set max discount to 10%
6. Create account

### Promoting Sales to Manager
1. Find user in User Management
2. Click "Edit"
3. Change role to "Manager"
4. Enable: View Reports, Manage Inventory, Manage Suppliers
5. Increase max discount to 20%
6. Save changes

### Temporarily Suspending an Employee
1. Find user in User Management
2. Click "Delete"
3. Choose "Deactivate"
4. User cannot log in but data is preserved

### Viewing Sales Performance
1. Find user in User Management
2. Click "View Details" (eye icon)
3. See sales statistics and recent transactions

## Troubleshooting

### "Permission Denied" Error
- Check if your account has "Manage Users" permission
- Only Administrators and Superusers can access User Management

### Cannot Create User - Username Already Exists
- Each username must be unique
- Check if user already exists in the system
- Try a different username format

### User Cannot Log In
- Verify account is **Active** (not deactivated)
- Check if password was set correctly
- Ensure user profile was created (happens automatically)

### Permissions Not Working
- Changes take effect immediately, but user may need to log out and back in
- Verify permission checkboxes are saved properly
- Check role assignment - some roles have default permission sets

### Missing Django Admin Access
- Enable "Staff Status" checkbox when editing user
- Only administrators should have admin panel access

## Technical Details

### Files Created
- **Views**: `inventory/user_management_views.py`
- **Templates**: `templates/inventory/user_management/`
  - `dashboard.html` - Main user list
  - `user_form.html` - Create/edit user form
  - `user_detail.html` - User detail view
  - `role_templates.html` - Role documentation
- **URLs**: Added to `inventory/urls.py`

### URL Structure
- `/user-management/` - Main dashboard
- `/user-management/create/` - Create new user
- `/user-management/<id>/` - View user details
- `/user-management/<id>/edit/` - Edit user
- `/user-management/<id>/delete/` - Delete/deactivate user
- `/user-management/roles/` - Role templates

### Database Models
- **User**: Django built-in User model (username, password, email, name)
- **UserProfile**: Extended profile (role, permissions, created_date)
  - Automatically created when User is created via signal

### Permissions Logic
Permissions are checked at multiple levels:
1. **View Level**: `@user_passes_test(is_admin)` decorator
2. **Template Level**: `{% if user.profile.can_manage_users %}`
3. **Navigation**: Menu items hidden based on role

## Integration with Django Admin

The new User Management interface **does not replace** the Django admin panel. Both can be used:

**Use the Visual Interface For**:
- Creating users
- Assigning roles
- Managing permissions
- Viewing user activity
- Non-technical admin tasks

**Use Django Admin For**:
- Advanced configuration
- Bulk operations
- Database-level changes
- Technical troubleshooting
- Direct model editing

Both interfaces work with the same data - changes in one are reflected in the other immediately.

## Support

For technical support or feature requests:
1. Check this guide first
2. Review the Role Templates page for permission details
3. Contact system administrator
4. For bugs, check: https://github.com/anthropics/claude-code/issues

---

**Version**: 1.0
**Last Updated**: 2025-11-05
**Compatible With**: IMS Django Inventory Management System v2.0+
