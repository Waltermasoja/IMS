"""
Utility functions for Import Order & Landed Cost System
Includes expense allocation algorithms and exchange rate integration
"""

import requests
from decimal import Decimal, ROUND_HALF_UP
from django.utils import timezone
from django.db.models import Sum
from django.conf import settings
import logging

logger = logging.getLogger(__name__)


# ==================== SITE SETTINGS HELPER ====================

def get_site_settings():
    """
    Get the site settings singleton instance.
    Uses caching for performance - call this instead of SiteSettings.get_settings()
    from utility functions to avoid circular imports.
    """
    from .models import SiteSettings
    return SiteSettings.get_settings()


def get_setting(setting_name, default=None):
    """
    Get a specific setting value by name.
    Returns the default if setting doesn't exist.

    Usage:
        low_stock = get_setting('low_stock_threshold', 10)
        markup = get_setting('default_markup_percent', 40)
    """
    try:
        settings_obj = get_site_settings()
        return getattr(settings_obj, setting_name, default)
    except Exception:
        return default

# ==================== EXCHANGE RATE INTEGRATION ====================

def get_exchange_rate(from_currency, to_currency='USD'):
    """
    Fetch current exchange rate from external API
    Falls back to manual rates if API fails
    """
    if from_currency == to_currency:
        return Decimal('1.0000')
    
    try:
        # Using exchangerate-api.com (free tier: 1500 requests/month)
        api_url = f"https://api.exchangerate-api.com/v4/latest/{from_currency}"
        
        response = requests.get(api_url, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        rate = data['rates'].get(to_currency)
        
        if rate:
            return Decimal(str(rate)).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)
        
    except (requests.RequestException, KeyError, ValueError) as e:
        logger.warning(f"Failed to fetch exchange rate for {from_currency} to {to_currency}: {e}")
    
    # Fallback to manual rates (update these periodically)
    fallback_rates = {
        'USD_ZAR': Decimal('18.50'),
        'USD_GBP': Decimal('0.79'),
        'USD_EUR': Decimal('0.92'),
        'USD_CNY': Decimal('7.25'),
        'ZAR_USD': Decimal('0.054'),
        'GBP_USD': Decimal('1.27'),
        'EUR_USD': Decimal('1.09'),
        'CNY_USD': Decimal('0.138'),
    }
    
    rate_key = f"{from_currency}_{to_currency}"
    reverse_key = f"{to_currency}_{from_currency}"
    
    if rate_key in fallback_rates:
        return fallback_rates[rate_key]
    elif reverse_key in fallback_rates:
        return Decimal('1') / fallback_rates[reverse_key]
    
    logger.error(f"No exchange rate available for {from_currency} to {to_currency}")
    return Decimal('1.0000')  # Default fallback

def get_common_expenses_for_country(country):
    """
    Return common expense types and estimated percentages for a country
    """
    expense_templates = {
        'China': [
            {'type': 'SHIPPING', 'description': 'Sea freight from China', 'estimated_percentage': 15},
            {'type': 'CUSTOMS_DUTY', 'description': 'Import duty', 'estimated_percentage': 10},
            {'type': 'VAT', 'description': 'Value Added Tax', 'estimated_percentage': 15},
            {'type': 'CLEARING_AGENT', 'description': 'Customs clearing', 'estimated_percentage': 3},
            {'type': 'TRANSPORT', 'description': 'Local transport', 'estimated_percentage': 5},
        ],
        'South Africa': [
            {'type': 'TRANSPORT', 'description': 'Road transport', 'estimated_percentage': 8},
            {'type': 'CUSTOMS_DUTY', 'description': 'SACU duty', 'estimated_percentage': 5},
            {'type': 'VAT', 'description': 'VAT 15%', 'estimated_percentage': 15},
            {'type': 'CLEARING_AGENT', 'description': 'Clearing agent', 'estimated_percentage': 2},
        ],
        'United Kingdom': [
            {'type': 'SHIPPING', 'description': 'Air freight', 'estimated_percentage': 20},
            {'type': 'CUSTOMS_DUTY', 'description': 'UK import duty', 'estimated_percentage': 8},
            {'type': 'VAT', 'description': 'UK VAT 20%', 'estimated_percentage': 20},
            {'type': 'HANDLING', 'description': 'Handling fee', 'estimated_percentage': 2},
        ],
        'United States': [
            {'type': 'SHIPPING', 'description': 'Freight charges', 'estimated_percentage': 12},
            {'type': 'CUSTOMS_DUTY', 'description': 'US import duty', 'estimated_percentage': 6},
            {'type': 'CLEARING_AGENT', 'description': 'Customs broker', 'estimated_percentage': 3},
            {'type': 'TRANSPORT', 'description': 'Inland transport', 'estimated_percentage': 4},
        ]
    }
    
    return expense_templates.get(country, [
        {'type': 'SHIPPING', 'description': 'Shipping charges', 'estimated_percentage': 15},
        {'type': 'CUSTOMS_DUTY', 'description': 'Import duty', 'estimated_percentage': 10},
        {'type': 'VAT', 'description': 'Tax/VAT', 'estimated_percentage': 15},
    ])

# ==================== EXPENSE ALLOCATION ALGORITHMS ====================

def allocate_expenses_by_value(import_order):
    """
    Distribute expenses proportionally based on item value
    Most fair for mixed-value shipments
    """
    from .models import ImportOrderItem

    items = import_order.items.all()
    if not items:
        return False

    total_goods_value = sum(item.quantity * item.unit_cost for item in items)
    total_expenses = import_order.total_expenses

    if total_goods_value == 0:
        return False

    for item in items:
        item_value = item.quantity * item.unit_cost
        proportion = item_value / total_goods_value
        item.allocated_expenses = total_expenses * proportion


        # Save old selling price before updating (for price comparison)
        if item.inventory_item:
            item.old_selling_price = item.inventory_item.selling_price

        item.save()

        # Update inventory with landed cost
        item.inventory_item.purchase_price = item.landed_cost_per_unit
        item.inventory_item.selling_price = item.suggested_selling_price
        item.inventory_item.save()

    # Update goods cost and mark allocation as completed
    import_order.goods_cost = total_goods_value
    import_order.allocation_completed = True
    import_order.allocation_date = timezone.now()
    import_order.save()

    return True

def allocate_expenses_by_quantity(import_order):
    """
    Distribute expenses equally per unit
    Good for similar products
    """
    items = import_order.items.all()
    if not items:
        return False

    total_quantity = sum(item.quantity for item in items)
    total_expenses = import_order.total_expenses

    if total_quantity == 0:
        return False

    expense_per_unit = total_expenses / total_quantity

    for item in items:
        item.allocated_expenses = expense_per_unit * item.quantity

        # Save old selling price before updating (for price comparison)
        if item.inventory_item:
            item.old_selling_price = item.inventory_item.selling_price

        item.save()

        # Update inventory with landed cost
        item.inventory_item.purchase_price = item.landed_cost_per_unit
        item.inventory_item.selling_price = item.suggested_selling_price
        item.inventory_item.save()

    # Update goods cost and mark allocation as completed
    total_goods_value = sum(item.quantity * item.unit_cost for item in items)
    import_order.goods_cost = total_goods_value
    import_order.allocation_completed = True
    import_order.allocation_date = timezone.now()
    import_order.save()

    return True

def allocate_expenses_by_weight(import_order):
    """
    Distribute expenses based on weight
    Good when shipping cost is primarily by weight
    """
    items = import_order.items.all()
    if not items:
        return False

    total_weight = sum(item.quantity * item.inventory_item.weight for item in items)
    total_expenses = import_order.total_expenses

    if total_weight == 0:
        # Fallback to quantity if no weights set
        return allocate_expenses_by_quantity(import_order)

    for item in items:
        item_weight = item.quantity * item.inventory_item.weight
        proportion = item_weight / total_weight
        item.allocated_expenses = total_expenses * proportion

        # Save old selling price before updating (for price comparison)
        if item.inventory_item:
            item.old_selling_price = item.inventory_item.selling_price

        item.save()

        # Update inventory with landed cost
        item.inventory_item.purchase_price = item.landed_cost_per_unit
        item.inventory_item.selling_price = item.suggested_selling_price
        item.inventory_item.save()

    # Update goods cost and mark allocation as completed
    total_goods_value = sum(item.quantity * item.unit_cost for item in items)
    import_order.goods_cost = total_goods_value
    import_order.allocation_completed = True
    import_order.allocation_date = timezone.now()
    import_order.save()

    return True

def allocate_expenses_smart(import_order):
    """
    Smart allocation: Different methods for different expense types
    - Shipping/Freight → By weight
    - Customs/VAT → By value  
    - Fixed fees → By quantity
    """
    items = import_order.items.all()
    if not items:
        return False
    
    # Calculate totals
    total_value = sum(item.quantity * item.unit_cost for item in items)
    total_quantity = sum(item.quantity for item in items)
    total_weight = sum(item.quantity * item.inventory_item.weight for item in items)
    
    # Initialize allocated expenses for each item
    for item in items:
        item.allocated_expenses = Decimal('0')
    
    # Process each expense type differently
    for expense in import_order.expenses.all():
        expense_amount = expense.amount_in_local
        
        if expense.expense_type in ['SHIPPING', 'TRANSPORT', 'INSURANCE']:
            # Allocate by weight (or quantity if no weights)
            if total_weight > 0:
                for item in items:
                    item_weight = item.quantity * item.inventory_item.weight
                    proportion = item_weight / total_weight
                    item.allocated_expenses += expense_amount * proportion
            elif total_quantity > 0:
                expense_per_unit = expense_amount / total_quantity
                for item in items:
                    item.allocated_expenses += expense_per_unit * item.quantity
                    
        elif expense.expense_type in ['CUSTOMS_DUTY', 'VAT']:
            # Allocate by value
            if total_value > 0:
                for item in items:
                    item_value = item.quantity * item.unit_cost
                    proportion = item_value / total_value
                    item.allocated_expenses += expense_amount * proportion
                    
        else:
            # Fixed fees by quantity
            if total_quantity > 0:
                expense_per_unit = expense_amount / total_quantity
                for item in items:
                    item.allocated_expenses += expense_per_unit * item.quantity
    
    # Save all items and update inventory
    for item in items:
        # Save old selling price before updating (for price comparison)
        if item.inventory_item:
            item.old_selling_price = item.inventory_item.selling_price

        item.save()

        # Update inventory with landed cost
        item.inventory_item.purchase_price = item.landed_cost_per_unit
        item.inventory_item.selling_price = item.suggested_selling_price
        item.inventory_item.save()

    # Update goods cost and mark allocation as completed
    import_order.goods_cost = total_value
    import_order.allocation_completed = True
    import_order.allocation_date = timezone.now()
    import_order.save()

    return True

def allocate_expenses_custom(import_order, percentages_dict):
    """
    Allow user to manually set percentage for each item
    percentages_dict = {item_id: percentage}
    """
    items = import_order.items.all()
    if not items:
        return False
    
    total_expenses = import_order.total_expenses
    
    # Validate percentages sum to 100
    total_percentage = sum(percentages_dict.values())
    if abs(total_percentage - 100) > 0.01:  # Allow small rounding differences
        return False
    
    for item in items:
        percentage = percentages_dict.get(item.id, 0)
        item.allocated_expenses = total_expenses * (Decimal(str(percentage)) / 100)
        item.save()
        
        # Update inventory with landed cost
        item.inventory_item.purchase_price = item.landed_cost_per_unit
        item.inventory_item.selling_price = item.suggested_selling_price
        item.inventory_item.save()
    
    # Mark allocation as completed
    import_order.allocation_completed = True
    import_order.allocation_date = timezone.now()
    import_order.save()
    
    return True

def run_allocation(import_order, method=None):
    """
    Main function to run expense allocation
    """
    if method is None:
        method = import_order.allocation_method
    
    allocation_functions = {
        'VALUE': allocate_expenses_by_value,
        'QUANTITY': allocate_expenses_by_quantity,
        'WEIGHT': allocate_expenses_by_weight,
        'SMART': allocate_expenses_smart,
    }
    
    allocation_func = allocation_functions.get(method)
    if allocation_func:
        return allocation_func(import_order)
    
    return False

# ==================== HELPER FUNCTIONS ====================

def calculate_estimated_expenses(goods_cost, country, currency='USD'):
    """
    Calculate estimated expenses based on goods cost and country
    """
    common_expenses = get_common_expenses_for_country(country)
    estimated_expenses = []
    
    for expense_template in common_expenses:
        estimated_amount = goods_cost * (expense_template['estimated_percentage'] / 100)
        estimated_expenses.append({
            'type': expense_template['type'],
            'description': expense_template['description'],
            'estimated_amount': estimated_amount,
            'currency': currency
        })
    
    return estimated_expenses

def generate_order_number(year=None):
    """
    Generate next available order number for the year
    """
    from .models import ImportOrder
    
    if year is None:
        year = timezone.now().year
    
    last_order = ImportOrder.objects.filter(
        order_date__year=year
    ).order_by('-order_number').first()
    
    if last_order and last_order.order_number:
        try:
            last_num = int(last_order.order_number.split('-')[-1])
            new_num = last_num + 1
        except (ValueError, IndexError):
            new_num = 1
    else:
        new_num = 1
    
    return f"IO-{year}-{new_num:04d}"

def calculate_due_date(invoice_date, payment_terms):
    """
    Calculate due date based on payment terms
    """
    from datetime import timedelta
    
    terms_mapping = {
        'NET 7': 7,
        'NET 15': 15,
        'NET 30': 30,
        'NET 45': 45,
        'NET 60': 60,
        'NET 90': 90,
        'COD': 0,  # Cash on Delivery
        'PREPAID': 0,  # Already paid
    }
    
    days = terms_mapping.get(payment_terms.upper(), 30)  # Default to 30 days
    return invoice_date + timedelta(days=days)

def get_overdue_invoices():
    """
    Get all overdue invoices for dashboard alerts
    """
    from .models import SupplierInvoice
    
    return SupplierInvoice.objects.filter(
        due_date__lt=timezone.now().date(),
        status__in=['PENDING', 'PARTIAL']
    ).select_related('import_order__supplier')

def get_low_stock_items_from_imports():
    """
    Get inventory items that were imported and are now low in stock
    """
    from .models import Inventory
    
    return Inventory.objects.filter(
        import_history__isnull=False,  # Has import history
        quantity_in_Stock__lte=10  # Low stock threshold
    ).distinct().select_related('category')

def calculate_import_profitability(import_order):
    """
    Calculate profitability metrics for an import order
    """
    items = import_order.items.all()
    
    total_landed_cost = sum(item.landed_cost_per_unit * item.quantity for item in items)
    total_selling_price = sum(item.suggested_selling_price * item.quantity for item in items)
    
    profit = total_selling_price - total_landed_cost
    profit_margin = (profit / total_selling_price * 100) if total_selling_price > 0 else 0
    
    return {
        'total_landed_cost': total_landed_cost,
        'total_selling_price': total_selling_price,
        'profit': profit,
        'profit_margin': profit_margin,
        'items_count': len(items)
    }
