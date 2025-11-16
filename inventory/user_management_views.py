"""
User Management Views
Provides visual interface for managing users, roles, and permissions
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.contrib.auth.models import User
from django.db.models import Q, Count, Sum
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from .models import UserProfile, Sales
from decimal import Decimal
import json


def is_admin(user):
    """Check if user is admin or superuser"""
    return user.is_superuser or (hasattr(user, 'profile') and user.profile.is_admin)


@login_required
@user_passes_test(is_admin)
def user_management_dashboard(request):
    """Main dashboard for user management"""
    users = User.objects.select_related('profile').annotate(
        total_sales=Count('sales_made'),
        sales_amount=Sum('sales_made__total_amount')
    ).order_by('-date_joined')

    # Statistics
    total_users = users.count()
    active_users = users.filter(is_active=True).count()
    admin_users = users.filter(Q(is_superuser=True) | Q(profile__role='admin')).count()
    sales_users = users.filter(profile__role='sales').count()

    context = {
        'users': users,
        'total_users': total_users,
        'active_users': active_users,
        'admin_users': admin_users,
        'sales_users': sales_users,
    }

    return render(request, 'inventory/user_management/dashboard.html', context)


@login_required
@user_passes_test(is_admin)
def user_create(request):
    """Create a new user with profile"""
    if request.method == 'POST':
        # Extract form data
        username = request.POST.get('username')
        email = request.POST.get('email')
        first_name = request.POST.get('first_name')
        last_name = request.POST.get('last_name')
        password = request.POST.get('password')
        password_confirm = request.POST.get('password_confirm')

        # Role and permissions
        role = request.POST.get('role', 'sales')
        is_active = request.POST.get('is_active') == 'on'
        is_staff = request.POST.get('is_staff') == 'on'

        # Validate
        if not username or not password:
            messages.error(request, 'Username and password are required')
            return redirect('user_create')

        if password != password_confirm:
            messages.error(request, 'Passwords do not match')
            return redirect('user_create')

        if User.objects.filter(username=username).exists():
            messages.error(request, f'Username "{username}" already exists')
            return redirect('user_create')

        try:
            # Create user
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name,
                is_active=is_active,
                is_staff=is_staff
            )

            # Update profile (created automatically by signal)
            profile = user.profile
            profile.role = role

            # Permissions
            profile.can_make_sales = request.POST.get('can_make_sales') == 'on'
            profile.can_process_returns = request.POST.get('can_process_returns') == 'on'
            profile.can_apply_discounts = request.POST.get('can_apply_discounts') == 'on'
            profile.max_discount_percent = Decimal(request.POST.get('max_discount_percent', '10.00'))

            profile.can_view_reports = request.POST.get('can_view_reports') == 'on'
            profile.can_manage_inventory = request.POST.get('can_manage_inventory') == 'on'
            profile.can_manage_suppliers = request.POST.get('can_manage_suppliers') == 'on'
            profile.can_manage_users = request.POST.get('can_manage_users') == 'on'

            profile.save()

            messages.success(request, f'User "{username}" created successfully')
            return redirect('user_management_dashboard')

        except Exception as e:
            messages.error(request, f'Error creating user: {str(e)}')
            return redirect('user_create')

    return render(request, 'inventory/user_management/user_form.html', {
        'action': 'Create',
        'roles': UserProfile.USER_ROLES,
    })


@login_required
@user_passes_test(is_admin)
def user_edit(request, user_id):
    """Edit existing user and profile"""
    user = get_object_or_404(User, pk=user_id)

    # Prevent editing superuser by non-superuser
    if user.is_superuser and not request.user.is_superuser:
        messages.error(request, 'You cannot edit a superuser account')
        return redirect('user_management_dashboard')

    if request.method == 'POST':
        # Update user fields
        user.email = request.POST.get('email', '')
        user.first_name = request.POST.get('first_name', '')
        user.last_name = request.POST.get('last_name', '')
        user.is_active = request.POST.get('is_active') == 'on'
        user.is_staff = request.POST.get('is_staff') == 'on'

        # Update password if provided
        new_password = request.POST.get('password')
        if new_password:
            password_confirm = request.POST.get('password_confirm')
            if new_password == password_confirm:
                user.set_password(new_password)
            else:
                messages.error(request, 'Passwords do not match')
                return redirect('user_edit', user_id=user_id)

        user.save()

        # Update profile
        profile = user.profile
        profile.role = request.POST.get('role', 'sales')

        # Permissions
        profile.can_make_sales = request.POST.get('can_make_sales') == 'on'
        profile.can_process_returns = request.POST.get('can_process_returns') == 'on'
        profile.can_apply_discounts = request.POST.get('can_apply_discounts') == 'on'
        profile.max_discount_percent = Decimal(request.POST.get('max_discount_percent', '10.00'))

        profile.can_view_reports = request.POST.get('can_view_reports') == 'on'
        profile.can_manage_inventory = request.POST.get('can_manage_inventory') == 'on'
        profile.can_manage_suppliers = request.POST.get('can_manage_suppliers') == 'on'
        profile.can_manage_users = request.POST.get('can_manage_users') == 'on'

        profile.save()

        messages.success(request, f'User "{user.username}" updated successfully')
        return redirect('user_management_dashboard')

    context = {
        'action': 'Edit',
        'edit_user': user,
        'roles': UserProfile.USER_ROLES,
    }

    return render(request, 'inventory/user_management/user_form.html', context)


@login_required
@user_passes_test(is_admin)
def user_delete(request, user_id):
    """Deactivate or delete a user"""
    if request.method == 'POST':
        user = get_object_or_404(User, pk=user_id)

        # Prevent deleting self
        if user == request.user:
            messages.error(request, 'You cannot delete your own account')
            return redirect('user_management_dashboard')

        # Prevent deleting superuser by non-superuser
        if user.is_superuser and not request.user.is_superuser:
            messages.error(request, 'You cannot delete a superuser account')
            return redirect('user_management_dashboard')

        action = request.POST.get('action', 'deactivate')

        if action == 'delete':
            username = user.username
            user.delete()
            messages.success(request, f'User "{username}" has been deleted')
        else:
            user.is_active = False
            user.save()
            messages.success(request, f'User "{user.username}" has been deactivated')

        return redirect('user_management_dashboard')

    return redirect('user_management_dashboard')


@login_required
@user_passes_test(is_admin)
def user_detail(request, user_id):
    """View detailed user information and activity"""
    user = get_object_or_404(User, pk=user_id)

    # Get user's sales statistics
    recent_sales = user.sales_made.order_by('-sale_date')[:10]

    from django.utils import timezone
    from datetime import timedelta

    thirty_days_ago = timezone.now() - timedelta(days=30)

    sales_stats = {
        'total_sales': user.sales_made.count(),
        'total_amount': user.sales_made.aggregate(
            total=Sum('total_amount'))['total'] or 0,
        'sales_this_month': user.sales_made.filter(
            sale_date__gte=thirty_days_ago
        ).count(),
        'amount_this_month': user.sales_made.filter(
            sale_date__gte=thirty_days_ago
        ).aggregate(total=Sum('total_amount'))['total'] or 0,
    }

    context = {
        'view_user': user,
        'recent_sales': recent_sales,
        'sales_stats': sales_stats,
    }

    return render(request, 'inventory/user_management/user_detail.html', context)


@login_required
@user_passes_test(is_admin)
def user_toggle_active(request, user_id):
    """Quick toggle user active status"""
    if request.method == 'POST':
        user = get_object_or_404(User, pk=user_id)

        if user == request.user:
            return JsonResponse({'success': False, 'error': 'Cannot deactivate yourself'})

        if user.is_superuser and not request.user.is_superuser:
            return JsonResponse({'success': False, 'error': 'Cannot modify superuser'})

        user.is_active = not user.is_active
        user.save()

        return JsonResponse({
            'success': True,
            'is_active': user.is_active,
            'message': f'User {"activated" if user.is_active else "deactivated"}'
        })

    return JsonResponse({'success': False, 'error': 'Invalid request'})


@login_required
@user_passes_test(is_admin)
def user_permissions_quick_edit(request, user_id):
    """Quick edit permissions via AJAX"""
    if request.method == 'POST':
        user = get_object_or_404(User, pk=user_id)
        profile = user.profile

        try:
            data = json.loads(request.body)
            permission = data.get('permission')
            value = data.get('value')

            if hasattr(profile, permission):
                setattr(profile, permission, value)
                profile.save()

                return JsonResponse({
                    'success': True,
                    'message': f'Permission updated'
                })
            else:
                return JsonResponse({
                    'success': False,
                    'error': 'Invalid permission'
                })

        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            })

    return JsonResponse({'success': False, 'error': 'Invalid request'})


@login_required
@user_passes_test(is_admin)
def role_templates(request):
    """View and manage role templates"""

    role_descriptions = {
        'admin': {
            'name': 'Administrator',
            'description': 'Full system access including user management and system settings',
            'permissions': [
                'can_make_sales', 'can_process_returns', 'can_apply_discounts',
                'can_view_reports', 'can_manage_inventory', 'can_manage_suppliers',
                'can_manage_users'
            ],
            'color': 'red'
        },
        'manager': {
            'name': 'Manager',
            'description': 'Operational control over inventory, sales, and basic finance',
            'permissions': [
                'can_make_sales', 'can_process_returns', 'can_apply_discounts',
                'can_view_reports', 'can_manage_inventory', 'can_manage_suppliers'
            ],
            'color': 'blue'
        },
        'sales': {
            'name': 'Sales Associate',
            'description': 'Point of sale operations and customer service',
            'permissions': [
                'can_make_sales', 'can_process_returns', 'can_apply_discounts'
            ],
            'color': 'green'
        },
        'viewer': {
            'name': 'Viewer',
            'description': 'Read-only access to reports and inventory',
            'permissions': ['can_view_reports'],
            'color': 'gray'
        }
    }

    context = {
        'roles': role_descriptions
    }

    return render(request, 'inventory/user_management/role_templates.html', context)
