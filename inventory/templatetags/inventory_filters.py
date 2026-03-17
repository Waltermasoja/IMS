from django import template
from decimal import Decimal, InvalidOperation

register = template.Library()

@register.filter
def get_item(dictionary, key):
    return dictionary.get(key, 0.00)

@register.filter
def mul(value, arg):
    """Multiply two numeric values safely in templates."""
    try:
        return Decimal(value) * Decimal(arg)
    except (TypeError, ValueError, InvalidOperation):
        try:
            return float(value) * float(arg)
        except (TypeError, ValueError):
            return 0