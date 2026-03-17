"""
Context processors for the inventory app.
Makes site settings available in all templates.
"""

from .models import SiteSettings


def site_settings(request):
    """
    Add site settings to the template context.

    Usage in templates:
        {{ site_settings.company_name }}
        {{ site_settings.currency_symbol }}
        {{ site_settings.format_currency(100) }}
    """
    try:
        settings = SiteSettings.get_settings()
        return {
            'site_settings': settings,
        }
    except Exception:
        # Return empty dict if settings can't be loaded (e.g., during migrations)
        return {
            'site_settings': None,
        }
