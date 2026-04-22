from django.db import models, transaction
from django.utils import timezone
from django.db.models import Sum
from decimal import Decimal
from datetime import timedelta
import calendar
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from django_resized import ResizedImageField
from django.core.exceptions import ValidationError
from django.core.cache import cache
from django.core.validators import MinValueValidator


# ==================== SITE SETTINGS (SINGLETON) ====================

class SiteSettings(models.Model):
    """
    Singleton model for site-wide settings.
    Only one instance should exist - use SiteSettings.get_settings() to access.
    """

    CURRENCY_CHOICES = [
        ('USD', 'US Dollar ($)'),
        ('ZAR', 'South African Rand (R)'),
        ('GBP', 'British Pound (£)'),
        ('EUR', 'Euro (€)'),
        ('ZWL', 'Zimbabwe Dollar (Z$)'),
        ('BWP', 'Botswana Pula (P)'),
        ('KES', 'Kenyan Shilling (KSh)'),
        ('NGN', 'Nigerian Naira (₦)'),
    ]

    CURRENCY_SYMBOLS = {
        'USD': '$',
        'ZAR': 'R',
        'GBP': '£',
        'EUR': '€',
        'ZWL': 'Z$',
        'BWP': 'P',
        'KES': 'KSh',
        'NGN': '₦',
    }

    DATE_FORMAT_CHOICES = [
        ('Y-m-d', 'YYYY-MM-DD (2025-01-15)'),
        ('d/m/Y', 'DD/MM/YYYY (15/01/2025)'),
        ('m/d/Y', 'MM/DD/YYYY (01/15/2025)'),
        ('d-m-Y', 'DD-MM-YYYY (15-01-2025)'),
        ('d M Y', 'DD Mon YYYY (15 Jan 2025)'),
    ]

    FINANCIAL_YEAR_CHOICES = [
        (1, 'January'),
        (2, 'February'),
        (3, 'March'),
        (4, 'April'),
        (5, 'May'),
        (6, 'June'),
        (7, 'July'),
        (8, 'August'),
        (9, 'September'),
        (10, 'October'),
        (11, 'November'),
        (12, 'December'),
    ]

    # ==================== COMPANY INFORMATION ====================
    company_name = models.CharField(max_length=200, default='My Company',
                                    help_text="Your business name")
    company_address = models.TextField(blank=True,
                                       help_text="Full business address")
    company_phone = models.CharField(max_length=50, blank=True)
    company_email = models.EmailField(blank=True)
    company_website = models.URLField(blank=True)
    tax_registration_number = models.CharField(max_length=50, blank=True,
                                               help_text="VAT/TIN number")
    company_logo = models.ImageField(upload_to='company/', blank=True, null=True,
                                     help_text="Logo for receipts and invoices")

    # ==================== FINANCIAL SETTINGS ====================
    default_currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default='USD',
                                        help_text="Base currency for all transactions")
    currency_symbol_position = models.CharField(max_length=10, default='before',
                                                choices=[('before', 'Before ($100)'),
                                                        ('after', 'After (100$)')])
    decimal_places = models.IntegerField(default=2, choices=[(0, '0'), (2, '2')],
                                         help_text="Decimal places for prices")
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0,
                                   help_text="Default tax/VAT rate (%)")
    financial_year_start = models.IntegerField(choices=FINANCIAL_YEAR_CHOICES, default=1,
                                               help_text="Month financial year begins")

    # ==================== CREDIT & AR SETTINGS ====================
    default_credit_limit = models.DecimalField(max_digits=12, decimal_places=2, default=0,
                                               help_text="Default credit limit for new customers")
    default_payment_terms_days = models.IntegerField(default=30,
                                                     help_text="Default payment terms (Net X days)")
    credit_grace_period_days = models.IntegerField(default=0,
                                                   help_text="Days after due date before considered overdue")
    # Future: Interest settings
    enable_interest_charges = models.BooleanField(default=False,
                                                  help_text="Enable interest on overdue accounts")
    interest_rate_monthly = models.DecimalField(max_digits=5, decimal_places=2, default=0,
                                                help_text="Monthly interest rate (%) - for future use")

    # ==================== LAYBY SETTINGS ====================
    layby_minimum_deposit_percent = models.DecimalField(max_digits=5, decimal_places=2, default=20,
                                                        help_text="Minimum deposit required (%)")
    layby_max_duration_days = models.IntegerField(default=90,
                                                  help_text="Maximum days to complete layby")
    layby_cancellation_fee_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0,
                                                         help_text="Fee charged on layby cancellation (%)")

    # ==================== INVENTORY SETTINGS ====================
    low_stock_threshold = models.IntegerField(default=10,
                                              help_text="Default low stock warning level")
    default_markup_percent = models.DecimalField(max_digits=5, decimal_places=2, default=40,
                                                 help_text="Default markup percentage for new products")
    allow_negative_stock = models.BooleanField(default=False,
                                               help_text="Allow sales when stock is zero")
    track_stock_movements = models.BooleanField(default=True,
                                                help_text="Log all stock changes")

    # ==================== POS & SALES SETTINGS ====================
    receipt_prefix = models.CharField(max_length=10, default='RCP',
                                      help_text="Prefix for receipt numbers")
    invoice_prefix = models.CharField(max_length=10, default='INV',
                                      help_text="Prefix for invoice numbers")
    import_order_prefix = models.CharField(max_length=10, default='IO',
                                           help_text="Prefix for import order numbers")
    layby_prefix = models.CharField(max_length=10, default='LB',
                                    help_text="Prefix for layby plan numbers")
    max_discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=50,
                                               help_text="Maximum discount allowed (%)")
    require_customer_for_sales = models.BooleanField(default=False,
                                                     help_text="Require customer for all sales")
    print_receipt_automatically = models.BooleanField(default=False,
                                                      help_text="Auto-print receipt after sale")

    # ==================== DISPLAY SETTINGS ====================
    date_format = models.CharField(max_length=20, choices=DATE_FORMAT_CHOICES, default='Y-m-d')
    time_format = models.CharField(max_length=10, default='H:i',
                                   choices=[('H:i', '24-hour (14:30)'),
                                           ('h:i A', '12-hour (2:30 PM)')])
    items_per_page = models.IntegerField(default=25,
                                         choices=[(10, '10'), (25, '25'), (50, '50'), (100, '100')])

    # ==================== METADATA ====================
    created_date = models.DateTimeField(auto_now_add=True)
    last_updated = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        verbose_name = 'Site Settings'
        verbose_name_plural = 'Site Settings'

    def __str__(self):
        return f"Site Settings - {self.company_name}"

    def save(self, *args, **kwargs):
        # Ensure only one instance exists (singleton pattern)
        self.pk = 1
        super().save(*args, **kwargs)
        # Clear cache when settings are saved
        cache.delete('site_settings')

    def delete(self, *args, **kwargs):
        # Prevent deletion of settings
        pass

    @classmethod
    def get_settings(cls):
        """
        Get the singleton settings instance.
        Creates default settings if none exist.
        Uses caching for performance.
        """
        # Try to get from cache first
        settings = cache.get('site_settings')
        if settings is None:
            settings, created = cls.objects.get_or_create(pk=1)
            # Cache for 5 minutes
            cache.set('site_settings', settings, 300)
        return settings

    @property
    def currency_symbol(self):
        """Get the currency symbol for the default currency"""
        return self.CURRENCY_SYMBOLS.get(self.default_currency, '$')

    def format_currency(self, amount):
        """Format a number as currency according to settings"""
        if amount is None:
            amount = 0
        symbol = self.currency_symbol
        if self.decimal_places == 0:
            formatted = f"{amount:,.0f}"
        else:
            formatted = f"{amount:,.2f}"

        if self.currency_symbol_position == 'before':
            return f"{symbol}{formatted}"
        else:
            return f"{formatted}{symbol}"


def validate_image_size(image):
    """Validate uploaded image size (max 5MB)"""
    max_size_mb = 5
    if image.size > max_size_mb * 1024 * 1024:
        raise ValidationError(f'Image file too large (max {max_size_mb}MB)')


# ==================== MULTI-SHOP (PHASE A1) ====================

class Shop(models.Model):
    """
    A physical retail shop/branch. Stock, sales, cashbook, and financial
    statements are segregated by shop. Corporate-level entries (e.g. group
    expenses, inter-shop transfers) leave shop=NULL where the FK is nullable.
    """
    name = models.CharField(max_length=100)
    code = models.CharField(
        max_length=10, unique=True,
        help_text="Short code for receipts, SKUs, barcodes (e.g. 'BBY', 'CLO')",
    )
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=50, blank=True)
    manager = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='managed_shops',
    )
    is_active = models.BooleanField(default=True)
    vat_number_override = models.CharField(
        max_length=50, blank=True,
        help_text="Per-shop VAT number if different from SiteSettings (future ZIMRA per-shop registration)",
    )
    created_date = models.DateTimeField(auto_now_add=True)
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Shop'
        verbose_name_plural = 'Shops'

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if self.code:
            self.code = self.code.upper().strip()
        super().save(*args, **kwargs)


class UserProfile(models.Model):
    """Extended user profile for role-based access"""
    USER_ROLES = [
        ('admin', 'Administrator'),
        ('manager', 'Manager'),
        ('sales', 'Sales Associate'),
        ('viewer', 'Viewer Only'),
    ]
    
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(max_length=20, choices=USER_ROLES, default='sales')
    
    # POS Settings
    can_make_sales = models.BooleanField(default=True)
    can_process_returns = models.BooleanField(default=True)
    can_apply_discounts = models.BooleanField(default=True)
    max_discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=10.00,
                                              help_text="Maximum discount % this user can apply")
    
    # Access Control
    can_view_reports = models.BooleanField(default=False)
    can_manage_inventory = models.BooleanField(default=False)
    can_manage_suppliers = models.BooleanField(default=False)
    can_manage_users = models.BooleanField(default=False)

    # Shop assignment — drives POS shop selector default and scopes stock visibility
    default_shop = models.ForeignKey(
        'Shop', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='default_for_users',
        help_text="The shop this user operates at by default (cashiers pinned to their till's shop)",
    )

    # Metadata
    created_date = models.DateTimeField(auto_now_add=True)
    last_updated = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.user.username} - {self.get_role_display()}"
    
    @property
    def is_admin(self):
        return self.role == 'admin' or self.user.is_superuser
    
    @property
    def is_sales_person(self):
        return self.role == 'sales'
    
    @property
    def can_access_pos(self):
        # Admins and superusers always have POS access
        if self.is_admin or self.user.is_superuser:
            return True
        return self.can_make_sales and self.role in ['admin', 'manager', 'sales']

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    """Auto-create UserProfile when User is created"""
    if created:
        # Default role based on staff status
        role = 'admin' if instance.is_staff else 'sales'
        UserProfile.objects.create(
            user=instance,
            role=role,
            can_view_reports=instance.is_staff,
            can_manage_inventory=instance.is_staff,
            can_manage_suppliers=instance.is_staff,
            can_manage_users=instance.is_superuser
        )

@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    """Save UserProfile when User is saved"""
    if hasattr(instance, 'profile'):
        instance.profile.save()
    else:
        # Create profile if it doesn't exist
        role = 'admin' if instance.is_staff else 'sales'
        UserProfile.objects.create(
            user=instance,
            role=role,
            can_view_reports=instance.is_staff,
            can_manage_inventory=instance.is_staff,
            can_manage_suppliers=instance.is_staff,
            can_manage_users=instance.is_superuser
        )


@receiver(post_save, sender='inventory.Inventory')
def auto_generate_thumbnail(sender, instance, created, **kwargs):
    """Auto-generate thumbnail from main image if main image exists but thumbnail doesn't"""
    if instance.image and not instance.thumbnail:
        # Copy the main image to thumbnail field - django-resized will handle resizing
        instance.thumbnail = instance.image
        # Use update to avoid triggering another post_save signal
        Inventory.objects.filter(pk=instance.pk).update(thumbnail=instance.thumbnail)

class Inventory(models.Model):
    bought_from = models.CharField(max_length=100, blank=True, null=True)
    name = models.CharField(max_length=100)
    product_code = models.CharField(max_length=20, unique=True, blank=True, help_text="Unique product code for quick lookup")
    purchase_price = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True, default=0)
    selling_price = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True, default=0)
    quantity_in_Stock = models.IntegerField(default=0)
    description = models.TextField(blank=True)
    label = models.CharField(max_length=50, blank=True, null=True)
    size = models.CharField(max_length=20, blank=True, null=True)
    weight = models.DecimalField(max_digits=8, decimal_places=2, default=0, blank=True, null=True, help_text="Weight in kg")
    on_sale = models.BooleanField(default=True)
    category = models.ForeignKey('Inventory_category', on_delete=models.SET_NULL, null=True, blank=True)

    # Variant support
    has_variants = models.BooleanField(default=False, help_text="Enable if this product has size/color variants")
    variant_attributes = models.ManyToManyField('AttributeType', blank=True,
                                                help_text="Attribute types used for variants (e.g., Size, Color)")

    # Product Images - Optimized for performance
    image = ResizedImageField(
        size=[800, 600],
        quality=85,
        force_format='JPEG',
        upload_to='products/images/',
        blank=True,
        null=True,
        validators=[validate_image_size],
        help_text="Main product image (auto-resized to 800x600, max 5MB)"
    )
    thumbnail = ResizedImageField(
        size=[200, 200],
        quality=80,
        crop=['smart', 'smart'],  # Smart crop - detects faces/objects for better framing
        force_format='JPEG',
        upload_to='products/thumbnails/',
        blank=True,
        null=True,
        help_text="Thumbnail (auto-generated 200x200 with smart crop)"
    )
    
    # VAT
    is_vat_exempt = models.BooleanField(default=False, help_text="Zero-rated for VAT (e.g. basic foodstuffs)")

    # Stock control fields
    reorder_point = models.IntegerField(default=0, help_text="Minimum stock level before reordering")
    lead_time_days = models.IntegerField(default=0, help_text="Supplier lead time in days")

    source_import_order = models.ForeignKey('ImportOrder', on_delete=models.SET_NULL, null=True, blank=True,
                                           related_name='created_products',
                                           help_text="Import order this product was first added from")
    created_date = models.DateTimeField(auto_now_add=True)
    last_updated = models.DateTimeField(auto_now=True)
    last_sale_date = models.DateTimeField(null=True, blank=True)
    sales_record = models.ManyToManyField('Sales', related_name='inventory_items', blank=True)

    @property
    def total_sales(self):
        return self.sales_records.aggregate(total=models.Sum('total_amount'))['total'] or 0

    @property
    def total_quantity_sold(self):
        return self.sales_records.aggregate(total=models.Sum('quantity_sold'))['total'] or 0

    @property
    def total_stock(self):
        """
        Total stock across all variants (if has_variants) or direct stock.
        For products with variants, sums variant stock.
        For simple products, returns quantity_in_Stock.
        """
        if self.has_variants:
            return self.variants.filter(is_active=True).aggregate(
                total=models.Sum('quantity_in_stock')
            )['total'] or 0
        return self.quantity_in_Stock

    @property
    def variant_count(self):
        """Number of active variants"""
        if self.has_variants:
            return self.variants.filter(is_active=True).count()
        return 0

    @property
    def low_stock_variants(self):
        """Get variants that are at or below reorder point"""
        if self.has_variants:
            return self.variants.filter(
                is_active=True,
                quantity_in_stock__lte=models.F('reorder_point')
            )
        return self.variants.none()

    def get_variant_by_attributes(self, attribute_values):
        """
        Find a variant matching the given attribute values.
        attribute_values: list of AttributeValue IDs or instances
        """
        if not self.has_variants:
            return None

        # Convert to IDs if needed
        value_ids = set()
        for val in attribute_values:
            if hasattr(val, 'id'):
                value_ids.add(val.id)
            else:
                value_ids.add(val)

        # Find variant with exactly these attributes
        for variant in self.variants.filter(is_active=True):
            variant_attr_ids = set(variant.attribute_values.values_list('id', flat=True))
            if variant_attr_ids == value_ids:
                return variant

        return None

    def generate_product_code(self):
        """Auto-generate product code based on category and sequence"""
        if self.category:
            prefix = self.category.name[:3].upper()
        else:
            prefix = "GEN"  # General category
        
        # Find the last product with same prefix
        last_item = Inventory.objects.filter(
            product_code__startswith=prefix
        ).order_by('-product_code').first()
        
        if last_item and last_item.product_code:
            try:
                last_num = int(last_item.product_code.split('-')[-1])
                new_num = last_num + 1
            except (ValueError, IndexError):
                new_num = 1
        else:
            new_num = 1
        
        return f"{prefix}-{new_num:04d}"
    
    def save(self, *args, **kwargs):
        # Auto-generate product code if not provided
        if not self.product_code:
            self.product_code = self.generate_product_code()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = 'Inventory Item'
        verbose_name_plural = 'Inventory'

class Inventory_category(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    default_markup = models.DecimalField(max_digits=5, decimal_places=2, default=40, help_text="Default markup percentage for this category")
    date_created = models.DateTimeField(auto_now_add=True)
    date_updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


# ==================== PRODUCT VARIANTS SYSTEM ====================

class AttributeType(models.Model):
    """
    Defines types of attributes like Size, Color, Material, etc.
    Each attribute type can have multiple values.
    """
    name = models.CharField(max_length=50, unique=True)  # "Size", "Color"
    display_name = models.CharField(max_length=50)  # "Size", "Colour" (user-facing)
    display_order = models.IntegerField(default=0, help_text="Order in which attributes appear")
    is_active = models.BooleanField(default=True)
    created_date = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['display_order', 'name']
        verbose_name = 'Attribute Type'
        verbose_name_plural = 'Attribute Types'

    def __str__(self):
        return self.display_name


class AttributeValue(models.Model):
    """
    Individual values for an attribute type.
    E.g., Size: S, M, L, XL or Color: Black, White, Red
    """
    attribute_type = models.ForeignKey(AttributeType, on_delete=models.CASCADE, related_name='values')
    value = models.CharField(max_length=50)  # "Medium", "Black", "42"
    display_value = models.CharField(max_length=50, blank=True)  # Optional display name
    color_code = models.CharField(max_length=7, blank=True, help_text="Hex color code for color swatches (e.g., #000000)")
    display_order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['attribute_type', 'display_order', 'value']
        unique_together = ['attribute_type', 'value']
        verbose_name = 'Attribute Value'
        verbose_name_plural = 'Attribute Values'

    def __str__(self):
        return f"{self.attribute_type.name}: {self.display_value or self.value}"

    @property
    def label(self):
        """Return the display value or fall back to value"""
        return self.display_value or self.value


class ProductVariant(models.Model):
    """
    A specific variant of a product with its own SKU, price, and stock.
    E.g., "T-Shirt - Medium - Black"
    """
    product = models.ForeignKey('Inventory', on_delete=models.CASCADE, related_name='variants')
    sku = models.CharField(max_length=50, unique=True, help_text="Unique SKU for this variant")

    # Variant-specific pricing (can override parent product)
    purchase_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True,
                                         help_text="Leave blank to use product default")
    selling_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True,
                                        help_text="Leave blank to use product default")

    # Variant-specific stock
    quantity_in_stock = models.IntegerField(default=0)
    reorder_point = models.IntegerField(default=0, help_text="Minimum stock level before reordering")

    # Attributes for this variant (Size: M, Color: Black)
    attribute_values = models.ManyToManyField(AttributeValue, related_name='variants')

    # VAT (inherits from product when None)
    is_vat_exempt = models.BooleanField(null=True, blank=True,
                                        help_text="Override product VAT status. Leave blank to inherit.")

    # Status
    is_active = models.BooleanField(default=True)

    # Metadata
    created_date = models.DateTimeField(auto_now_add=True)
    last_updated = models.DateTimeField(auto_now=True)

    @property
    def effective_is_vat_exempt(self):
        if self.is_vat_exempt is not None:
            return self.is_vat_exempt
        return self.product.is_vat_exempt

    class Meta:
        ordering = ['product', 'sku']
        verbose_name = 'Product Variant'
        verbose_name_plural = 'Product Variants'

    def __str__(self):
        attrs = self.attribute_string
        if attrs:
            return f"{self.product.name} - {attrs}"
        return f"{self.product.name} ({self.sku})"

    @property
    def attribute_string(self):
        """Returns formatted string like 'M / Black'"""
        attrs = self.attribute_values.all().order_by('attribute_type__display_order')
        return " / ".join([attr.label for attr in attrs])

    @property
    def attribute_dict(self):
        """Returns dict like {'Size': 'M', 'Color': 'Black'}"""
        return {
            attr.attribute_type.name: attr.label
            for attr in self.attribute_values.all()
        }

    @property
    def effective_purchase_price(self):
        """Return variant price or fall back to product price"""
        if self.purchase_price is not None:
            return self.purchase_price
        return self.product.purchase_price or Decimal('0')

    @property
    def effective_selling_price(self):
        """Return variant price or fall back to product price"""
        if self.selling_price is not None:
            return self.selling_price
        return self.product.selling_price or Decimal('0')

    @property
    def is_low_stock(self):
        """Check if stock is at or below reorder point"""
        return self.quantity_in_stock <= self.reorder_point

    def generate_sku(self):
        """
        Auto-generate SKU based on product code and attribute values.
        E.g., TSH-0001-M-BLK
        """
        base_code = self.product.product_code or 'PROD'

        # Get attribute abbreviations
        abbrevs = []
        for attr in self.attribute_values.all().order_by('attribute_type__display_order'):
            # Take first 3 chars of value, uppercase
            abbrev = attr.value[:3].upper()
            abbrevs.append(abbrev)

        if abbrevs:
            return f"{base_code}-{'-'.join(abbrevs)}"
        return f"{base_code}-VAR"

    def save(self, *args, **kwargs):
        # Auto-generate SKU if not provided
        if not self.sku:
            # Need to save first to have access to M2M relationship
            if self.pk is None:
                # Temporary SKU, will be updated after M2M is set
                temp_sku = f"TEMP-{self.product.product_code or 'PROD'}-{timezone.now().timestamp()}"
                self.sku = temp_sku
        super().save(*args, **kwargs)


# ==================== PER-SHOP STOCK (PHASE A1) ====================

class ShopStock(models.Model):
    """
    Per-shop quantity on hand for a product (or a specific variant).

    This is the source of truth for stock counts once Phase A3 cuts the
    write paths over. Until then it co-exists with the legacy
    Inventory.quantity_in_Stock / ProductVariant.quantity_in_stock fields;
    nothing writes here automatically in Phase A1.

    Use ShopStock.get_or_create_for(shop, item, variant=None) to avoid
    leaking UNIQUE-violation paths into callers.
    """
    shop = models.ForeignKey('Shop', on_delete=models.PROTECT, related_name='stock_rows')
    inventory_item = models.ForeignKey('Inventory', on_delete=models.CASCADE, related_name='shop_stock')
    variant = models.ForeignKey(
        'ProductVariant', on_delete=models.CASCADE, null=True, blank=True,
        related_name='shop_stock',
    )
    quantity = models.IntegerField(default=0)
    reorder_point = models.IntegerField(
        default=0,
        help_text="Per-shop reorder point; 0 means fall back to product/variant level",
    )
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('shop', 'inventory_item', 'variant')]
        verbose_name = 'Shop Stock'
        verbose_name_plural = 'Shop Stock'
        ordering = ['shop', 'inventory_item']

    def __str__(self):
        target = self.variant.sku if self.variant else self.inventory_item.name
        return f"{self.shop.code}: {target} × {self.quantity}"

    @classmethod
    def get_or_create_for(cls, shop, inventory_item, variant=None):
        row, _ = cls.objects.get_or_create(
            shop=shop, inventory_item=inventory_item, variant=variant,
            defaults={'quantity': 0},
        )
        return row


class StockTransfer(models.Model):
    """
    Move stock from one shop to another.

    A transfer is created as DRAFT and must be executed via execute() to
    actually move the stock. execute() is atomic: it debits the source
    ShopStock, credits the destination, writes two StockMovement rows,
    and flips status to COMPLETED. Idempotent — a COMPLETED transfer
    will not be re-applied.
    """
    STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('COMPLETED', 'Completed'),
        ('CANCELLED', 'Cancelled'),
    ]
    from_shop = models.ForeignKey('Shop', on_delete=models.PROTECT, related_name='transfers_out')
    to_shop = models.ForeignKey('Shop', on_delete=models.PROTECT, related_name='transfers_in')
    inventory_item = models.ForeignKey('Inventory', on_delete=models.PROTECT)
    variant = models.ForeignKey('ProductVariant', on_delete=models.PROTECT, null=True, blank=True)
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    transferred_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='stock_transfers',
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='DRAFT')
    notes = models.TextField(blank=True)
    transferred_at = models.DateTimeField(default=timezone.now, db_index=True)
    created_date = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-transferred_at']
        verbose_name = 'Stock Transfer'
        verbose_name_plural = 'Stock Transfers'

    def __str__(self):
        target = self.variant.sku if self.variant else self.inventory_item.name
        return f"{target} × {self.quantity}: {self.from_shop.code} → {self.to_shop.code}"

    def clean(self):
        if self.from_shop_id and self.to_shop_id and self.from_shop_id == self.to_shop_id:
            raise ValidationError("from_shop and to_shop must be different")

    @transaction.atomic
    def execute(self):
        if self.status != 'DRAFT':
            return
        source = ShopStock.get_or_create_for(self.from_shop, self.inventory_item, self.variant)
        if source.quantity < self.quantity:
            raise ValidationError(
                f"Insufficient stock at {self.from_shop.code}: "
                f"have {source.quantity}, need {self.quantity}"
            )
        dest = ShopStock.get_or_create_for(self.to_shop, self.inventory_item, self.variant)
        source.quantity -= self.quantity
        dest.quantity += self.quantity
        source.save(update_fields=['quantity', 'last_updated'])
        dest.save(update_fields=['quantity', 'last_updated'])
        StockMovement.objects.create(
            inventory_item=self.inventory_item,
            movement_type='OUT',
            quantity=self.quantity,
            reason=f'Transfer to {self.to_shop.code} (#{self.pk})',
        )
        StockMovement.objects.create(
            inventory_item=self.inventory_item,
            movement_type='IN',
            quantity=self.quantity,
            reason=f'Transfer from {self.from_shop.code} (#{self.pk})',
        )
        self.status = 'COMPLETED'
        self.save(update_fields=['status'])


class Sales(models.Model):
    PAYMENT_METHODS = [
        ('CASH', 'Cash'),
        ('CREDIT', 'Credit'),
        ('LAYBY', 'Layby'),
    ]
    inventory_item = models.ForeignKey('Inventory', on_delete=models.PROTECT, related_name='sales_records')
    # Optional variant reference - if product has variants, this tracks which specific variant was sold
    product_variant = models.ForeignKey('ProductVariant', on_delete=models.SET_NULL, null=True, blank=True,
                                        related_name='sales_records',
                                        help_text="Specific variant sold (if product has variants)")
    quantity_sold = models.IntegerField(validators=[MinValueValidator(1)])
    sale_price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    sale_date = models.DateTimeField(default=timezone.now, db_index=True)
    discount_applied = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal('0.00'))])
    receipt_number = models.CharField(max_length=20, blank=True, null=True, unique=True)
    quantity_returned = models.IntegerField(default=0)
    payment_method = models.CharField(max_length=10, choices=PAYMENT_METHODS, default='CASH')
    recorded_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='sales_made')
    customer = models.ForeignKey('Customer', on_delete=models.SET_NULL, null=True, blank=True, related_name='sales')

    # Accounting posting flags
    posted_to_gl = models.BooleanField(default=False)
    posted_to_cashbook = models.BooleanField(default=False)

    @property
    def can_be_returned(self):
        return self.quantity_sold > self.quantity_returned

    @property
    def remaining_quantity(self):
        return self.quantity_sold - self.quantity_returned

    def save(self, *args, **kwargs):
        if not self.total_amount:
            discounted_price = self.sale_price * (1 - self.discount_applied / 100)
            self.total_amount = discounted_price * self.quantity_sold
        super().save(*args, **kwargs)

    class Meta:
        ordering = ['-sale_date']
        verbose_name = 'Sale'
        verbose_name_plural = 'Sales'

    def __str__(self):
        return f"Sale of {self.quantity_sold} {self.inventory_item.name}(s) on {self.sale_date.date()}"


# ============================================================
# Cart-based sales (SalesTicket + SalesLine)
# ============================================================
# Replaces the single-row Sales model. A ticket is one receipt with
# one or more lines. Money is stored VAT-inclusive on the line; VAT
# is backed out for the subtotal/vat columns at compute() time.
# Posting is handled by accounting.utils.post_ticket().

class SalesTicket(models.Model):
    TERMS_IMMEDIATE = 'IMMEDIATE'
    TERMS_CREDIT = 'CREDIT'
    TERMS_LAYBY = 'LAYBY'
    TERMS_CHOICES = [
        (TERMS_IMMEDIATE, 'Paid Immediately'),
        (TERMS_CREDIT, 'On Account (AR)'),
        (TERMS_LAYBY, 'Layby'),
    ]

    TENDER_CASH = 'CASH'
    TENDER_ECOCASH = 'ECOCASH'
    TENDER_BANK = 'BANK_TRANSFER'
    TENDER_CARD = 'CARD'
    TENDER_CHOICES = [
        (TENDER_CASH, 'Cash'),
        (TENDER_ECOCASH, 'EcoCash'),
        (TENDER_BANK, 'Bank Transfer'),
        (TENDER_CARD, 'Card'),
    ]

    receipt_number = models.CharField(max_length=32, unique=True, blank=True)
    shop = models.ForeignKey('Shop', on_delete=models.PROTECT, related_name='sales_tickets')
    cashier = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='tickets_rung',
    )
    customer = models.ForeignKey(
        'Customer', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='sales_tickets',
    )

    terms = models.CharField(max_length=12, choices=TERMS_CHOICES, default=TERMS_IMMEDIATE)
    tender_type = models.CharField(max_length=16, choices=TENDER_CHOICES, default=TENDER_CASH)
    tender_reference = models.CharField(
        max_length=100, blank=True,
        help_text='EcoCash agent code, bank transfer ref, or card auth number',
    )

    # Header totals — recomputed from lines via recalc_totals().
    subtotal_excl_vat = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))
    vat_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))
    discount_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))
    total_incl_vat = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))

    posted_to_gl = models.BooleanField(default=False)
    posted_to_cashbook = models.BooleanField(default=False)
    stock_posted = models.BooleanField(default=False)

    voided = models.BooleanField(default=False)
    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='tickets_voided',
    )

    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Sales Ticket'
        verbose_name_plural = 'Sales Tickets'

    def __str__(self):
        return f"{self.receipt_number or f'(unsaved)'} @ {self.shop.code}"

    def save(self, *args, **kwargs):
        if not self.receipt_number and self.shop_id:
            self.receipt_number = self._next_receipt_number()
        super().save(*args, **kwargs)

    def _next_receipt_number(self):
        today = timezone.localdate()
        prefix = f"{self.shop.code}-{today:%Y%m%d}-"
        existing = SalesTicket.objects.filter(
            receipt_number__startswith=prefix
        ).values_list('receipt_number', flat=True)
        max_seq = 0
        for num in existing:
            try:
                max_seq = max(max_seq, int(num.rsplit('-', 1)[1]))
            except (ValueError, IndexError):
                continue
        return f"{prefix}{max_seq + 1:04d}"

    def recalc_totals(self, save=True):
        agg = self.lines.aggregate(
            subtotal=Sum('line_subtotal_excl_vat'),
            vat=Sum('vat_amount'),
            discount=Sum('discount_amount'),
            total=Sum('line_total_incl_vat'),
        )
        self.subtotal_excl_vat = agg['subtotal'] or Decimal('0')
        self.vat_total = agg['vat'] or Decimal('0')
        self.discount_total = agg['discount'] or Decimal('0')
        self.total_incl_vat = agg['total'] or Decimal('0')
        if save:
            self.save(update_fields=[
                'subtotal_excl_vat', 'vat_total', 'discount_total',
                'total_incl_vat', 'updated_at',
            ])


class SalesLine(models.Model):
    ticket = models.ForeignKey(
        'SalesTicket', on_delete=models.CASCADE, related_name='lines',
    )
    inventory_item = models.ForeignKey(
        'Inventory', on_delete=models.PROTECT, related_name='ticket_lines',
    )
    variant = models.ForeignKey(
        'ProductVariant', on_delete=models.PROTECT, null=True, blank=True,
        related_name='ticket_lines',
    )
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])

    # VAT-inclusive shelf price snapshot.
    unit_price_incl_vat = models.DecimalField(max_digits=10, decimal_places=2)
    discount_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('0'),
        help_text='Currency discount on this line (not percent).',
    )
    # Snapshotted from the product at sale time. C1 will wire up the
    # per-product is_vat_exempt flag; until then tickets default to taxable.
    is_vat_exempt = models.BooleanField(default=False)
    vat_rate_applied = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0'))

    # Computed columns — populated by compute().
    line_subtotal_excl_vat = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))
    vat_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))
    line_total_incl_vat = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))

    # Captured unit cost for stable COGS even if product purchase_price changes later.
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0'))

    class Meta:
        ordering = ['id']
        verbose_name = 'Sales Line'
        verbose_name_plural = 'Sales Lines'

    def __str__(self):
        sku = self.variant.sku if self.variant else self.inventory_item.name
        return f"{self.quantity} × {sku}"

    def compute(self, vat_rate=None):
        if vat_rate is None:
            vat_rate = SiteSettings.get_settings().tax_rate or Decimal('0')
        self.vat_rate_applied = Decimal('0') if self.is_vat_exempt else Decimal(vat_rate)

        gross_incl = (self.unit_price_incl_vat * self.quantity) - self.discount_amount
        if gross_incl < 0:
            gross_incl = Decimal('0')

        if self.is_vat_exempt or self.vat_rate_applied == 0:
            self.vat_amount = Decimal('0')
            self.line_subtotal_excl_vat = gross_incl
        else:
            vat = (gross_incl * self.vat_rate_applied /
                   (Decimal('100') + self.vat_rate_applied)).quantize(Decimal('0.01'))
            self.vat_amount = vat
            self.line_subtotal_excl_vat = gross_incl - vat
        self.line_total_incl_vat = gross_incl

        if not self.unit_cost and self.inventory_item_id:
            self.unit_cost = self.inventory_item.purchase_price or Decimal('0')


class Return(models.Model):
    inventory_item = models.ForeignKey(Inventory, on_delete=models.PROTECT)
    quantity_returned = models.IntegerField(blank=False, null=False)
    return_date = models.DateField(auto_now_add=True)
    reason = models.TextField()
    receipt_number = models.CharField(max_length=20, blank=True, null=True)
    sale = models.ForeignKey('Sales', on_delete=models.SET_NULL, null=True, blank=True)
    shop = models.ForeignKey(
        'Shop', on_delete=models.PROTECT, null=True, blank=True,
        related_name='returns',
    )

    def __str__(self) -> str:
        return f'Return of {self.quantity_returned} {self.inventory_item.name}'

class Damaged(models.Model):
    inventory_item = models.ForeignKey('Inventory', on_delete=models.PROTECT)
    quantity_damaged = models.PositiveIntegerField()
    damage_description = models.TextField()
    shop = models.ForeignKey(
        'Shop', on_delete=models.PROTECT, null=True, blank=True,
        related_name='damaged_items',
    )

    def __str__(self):
        return f"{self.inventory_item.name} - {self.quantity_damaged} damaged"

class StockMovement(models.Model):
    inventory_item = models.ForeignKey(Inventory, on_delete=models.PROTECT)
    movement_type = models.CharField(max_length=3, choices=[('IN', 'In'), ('OUT', 'Out')])
    quantity = models.IntegerField(default=0, validators=[MinValueValidator(1)])
    reason = models.CharField(max_length=200,blank=True,null=True)
    stock_date = models.DateTimeField(auto_now_add=True, db_index=True)
    shop = models.ForeignKey(
        'Shop', on_delete=models.PROTECT, null=True, blank=True,
        related_name='stock_movements',
    )

    def __str__(self):
        return f"{self.movement_type} - {self.quantity} units of {self.inventory_item.name}"

    class Meta:
        ordering = ['-stock_date']

class missing_inventory(models.Model):
    inventory_item = models.ForeignKey(Inventory, on_delete=models.CASCADE)
    quantity_missing = models.IntegerField()
    missing_date = models.DateTimeField(auto_now_add=True)
    reason = models.TextField()
    shop = models.ForeignKey(
        'Shop', on_delete=models.PROTECT, null=True, blank=True,
        related_name='missing_inventory_records',
    )

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)

        if is_new and self.quantity_missing > 0:
            # Update inventory stock
            self.inventory_item.quantity_in_Stock -= self.quantity_missing
            self.inventory_item.save(update_fields=['quantity_in_Stock'])

            # Create stock movement
            StockMovement.objects.create(
                inventory_item=self.inventory_item,
                movement_type='OUT',
                quantity=self.quantity_missing,
                reason=f'Missing/Shrinkage: {self.reason}'
            )

            # Post GL entry: Dr COGS/Loss, Cr Inventory
            try:
                from accounting.utils import post_inventory_adjustment
                post_inventory_adjustment(
                    self.inventory_item,
                    self.quantity_missing,
                    self.reason or 'Missing inventory',
                    adjustment_type='SHRINKAGE',
                    user=None
                )
            except Exception as e:
                print(f"[SHRINKAGE] Warning: GL posting failed: {e}")

    def __str__(self):
        return f"Missing {self.quantity_missing} of {self.inventory_item.name}"

# ==================== IMPORT ORDER & LANDED COST SYSTEM ====================

class Supplier(models.Model):
    """Supplier/vendor management for import orders"""
    name = models.CharField(max_length=200)
    country = models.CharField(max_length=100)
    contact_person = models.CharField(max_length=100, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=50, blank=True)
    
    # Financial
    payment_terms = models.CharField(max_length=100, default="NET 30")
    currency_preference = models.CharField(max_length=3, default='USD', choices=[
        ('USD', 'US Dollar'),
        ('TRY', 'Turkish Lira'),
        ('RMB', 'Renminbi'),
        ('ZAR', 'South African Rand'),
        ('GBP', 'British Pound'),
        ('CNY', 'Chinese Yuan'),
        ('EUR', 'Euro')
    ])
    
    # Address
    address = models.TextField(blank=True)
    
    # Stats (auto-calculated)
    total_orders = models.IntegerField(default=0)
    total_spent = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    
    # Status
    is_active = models.BooleanField(default=True)
    
    created_date = models.DateTimeField(auto_now_add=True)
    last_updated = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['name']
    
    def __str__(self):
        return f"{self.name} ({self.country})"
    
    @property
    def outstanding_balance(self):
        """Total unpaid invoices"""
        return self.import_orders.aggregate(
            total=Sum('invoices__outstanding_amount')
        )['total'] or 0

class ImportOrder(models.Model):
    """Main import order tracking with landed cost calculation"""
    
    STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('CONFIRMED', 'Confirmed'),
        ('SHIPPED', 'Shipped'),
        ('IN_TRANSIT', 'In Transit'),
        ('CUSTOMS', 'Customs Clearance'),
        ('RECEIVED', 'Received'),
        ('COMPLETED', 'Completed'),
        ('CANCELLED', 'Cancelled')
    ]
    
    ALLOCATION_METHODS = [
        ('VALUE', 'By Value (Recommended)'),
        ('QUANTITY', 'By Quantity'),
        ('WEIGHT', 'By Weight'),
        ('SMART', 'Smart Allocation'),
        ('CUSTOM', 'Custom')
    ]
    
    # Basic Info
    order_number = models.CharField(max_length=50, unique=True, editable=False)
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name='import_orders')
    reference_number = models.CharField(max_length=100, blank=True, help_text="Supplier's order reference")
    
    # Dates
    order_date = models.DateField(default=timezone.now)
    expected_arrival = models.DateField()
    actual_arrival = models.DateField(null=True, blank=True)
    
    # Currency
    currency = models.CharField(max_length=3, default='USD', choices=[
        ('USD', 'US Dollar'),
        ('ZAR', 'South African Rand'),
        ('GBP', 'British Pound'),
        ('CNY', 'Chinese Yuan'),
        ('EUR', 'Euro')
    ])
    exchange_rate = models.DecimalField(max_digits=10, decimal_places=4, help_text="Rate to local currency")
    
    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT')
    
    # Costs
    goods_cost = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    
    # Allocation
    allocation_method = models.CharField(max_length=20, choices=ALLOCATION_METHODS, default='SMART')
    allocation_completed = models.BooleanField(default=False)
    allocation_date = models.DateTimeField(null=True, blank=True)
    
    # Metadata
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True)
    created_date = models.DateTimeField(auto_now_add=True)
    last_updated = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-order_date']
    
    def save(self, *args, **kwargs):
        if not self.order_number:
            # Auto-generate order number: IO-2025-001
            last_order = ImportOrder.objects.filter(
                order_date__year=self.order_date.year
            ).order_by('-order_number').first()
            
            if last_order and last_order.order_number:
                try:
                    last_num = int(last_order.order_number.split('-')[-1])
                    new_num = last_num + 1
                except (ValueError, IndexError):
                    new_num = 1
            else:
                new_num = 1
            
            self.order_number = f"IO-{self.order_date.year}-{new_num:04d}"
        
        super().save(*args, **kwargs)
    
    @property
    def total_expenses(self):
        return self.expenses.aggregate(total=Sum('amount_in_local'))['total'] or 0
    
    @property
    def total_landed_cost(self):
        return self.goods_cost + self.total_expenses
    
    @property
    def total_items_count(self):
        return self.items.aggregate(total=Sum('quantity'))['total'] or 0
    
    @property
    def payment_status(self):
        """Overall payment status"""
        invoices = self.invoices.all()
        if not invoices:
            return 'NO_INVOICE'
        
        total_invoice = sum(inv.total_amount for inv in invoices)
        total_paid = sum(inv.amount_paid for inv in invoices)
        
        if total_paid >= total_invoice:
            return 'PAID'
        elif total_paid > 0:
            return 'PARTIAL'
        else:
            return 'UNPAID'
    
    def receive_all_goods(self):
        """Receive all items in this import order and update stock"""
        from .utils import run_allocation
        
        # Run allocation first if not done
        if not self.allocation_completed:
            run_allocation(self)
        
        # Receive each item
        items_received = 0
        for item in self.items.all():
            if not item.is_received:
                item.receive_goods()
                items_received += 1
        
        # Update order status
        self.status = 'RECEIVED'
        self.actual_arrival = timezone.now().date()
        self.save()
        
        return items_received
    
    def __str__(self):
        return f"{self.order_number} - {self.supplier.name}"

class SupplierInvoice(models.Model):
    """Track supplier invoices with payment status"""
    
    INVOICE_STATUS = [
        ('PENDING', 'Pending'),
        ('PARTIAL', 'Partially Paid'),
        ('PAID', 'Paid'),
        ('OVERDUE', 'Overdue'),
        ('CANCELLED', 'Cancelled')
    ]
    
    # References
    import_order = models.ForeignKey(ImportOrder, on_delete=models.CASCADE, related_name='invoices')
    invoice_number = models.CharField(max_length=100, unique=True)
    
    # Amounts
    currency = models.CharField(max_length=3, default='USD')
    total_amount = models.DecimalField(max_digits=15, decimal_places=2)
    amount_paid = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    
    # Dates
    invoice_date = models.DateField()
    due_date = models.DateField()
    
    # Status
    status = models.CharField(max_length=20, choices=INVOICE_STATUS, default='PENDING')
    
    # Documents
    invoice_file = models.FileField(upload_to='invoices/', null=True, blank=True)
    
    # Metadata
    notes = models.TextField(blank=True)
    created_date = models.DateTimeField(auto_now_add=True)
    last_updated = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-invoice_date']
    
    @property
    def outstanding_amount(self):
        return self.total_amount - self.amount_paid
    
    @property
    def is_overdue(self):
        return self.due_date < timezone.now().date() and self.outstanding_amount > 0
    
    @property
    def days_overdue(self):
        if self.is_overdue:
            return (timezone.now().date() - self.due_date).days
        return 0
    
    def update_status(self):
        """Auto-update status based on payments"""
        if self.amount_paid >= self.total_amount:
            self.status = 'PAID'
        elif self.amount_paid > 0:
            self.status = 'PARTIAL'
        elif self.is_overdue:
            self.status = 'OVERDUE'
        else:
            self.status = 'PENDING'
        self.save()
    
    def __str__(self):
        return f"Invoice {self.invoice_number} - {self.import_order.supplier.name}"

class InvoicePayment(models.Model):
    """Track individual payments against invoices"""
    
    PAYMENT_METHODS = [
        ('BANK_TRANSFER', 'Bank Transfer'),
        ('WIRE', 'Wire Transfer'),
        ('CASH', 'Cash'),
        ('CHECK', 'Check'),
        ('CREDIT_CARD', 'Credit Card'),
        ('MOBILE_MONEY', 'Mobile Money'),
        ('OTHER', 'Other')
    ]
    
    invoice = models.ForeignKey(SupplierInvoice, on_delete=models.CASCADE, related_name='payments')
    
    # Payment details
    payment_date = models.DateField(default=timezone.now)
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS)
    
    # Reference
    reference_number = models.CharField(max_length=100, blank=True)
    
    # Bank details (if applicable)
    bank_name = models.CharField(max_length=100, blank=True)
    transaction_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    # Documents
    receipt_file = models.FileField(upload_to='payment_receipts/', null=True, blank=True)
    
    # Metadata
    notes = models.TextField(blank=True)
    recorded_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True)
    created_date = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-payment_date']
    
    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)

        # Auto-update invoice amount paid
        total_paid = self.invoice.payments.aggregate(total=Sum('amount'))['total'] or 0
        self.invoice.amount_paid = total_paid
        self.invoice.update_status()

        # Only post GL and cashbook for new payments
        if is_new:
            # Post to GL: Dr Accounts Payable, Cr Cash
            try:
                from accounting.utils import post_supplier_payment
                post_supplier_payment(self, user=self.recorded_by)
            except Exception as e:
                print(f"[SUPPLIER] Warning: GL posting failed for payment {self.id}: {e}")

            # Create cashbook payment entry (supplier payment)
            try:
                CashbookEntry.objects.create(
                    date=self.payment_date,
                    reference=self.reference_number or self.invoice.invoice_number,
                    description=f"Supplier payment - {self.invoice.import_order.supplier.name}",
                    receipt_amount=0,
                    payment_amount=self.amount,
                    category='SUPPLIER',
                    recorded_by=self.recorded_by,
                )
            except Exception:
                pass
    
    def __str__(self):
        return f"Payment of {self.amount} on {self.payment_date}"

class ImportExpense(models.Model):
    """Individual expenses for an import order"""
    
    EXPENSE_TYPES = [
        ('SHIPPING', 'Shipping/Freight'),
        ('CUSTOMS_DUTY', 'Customs Duty'),
        ('VAT', 'VAT/Tax'),
        ('CLEARING_AGENT', 'Clearing Agent Fee'),
        ('TRANSPORT', 'Local Transport'),
        ('INSURANCE', 'Insurance'),
        ('STORAGE', 'Storage/Warehousing'),
        ('BANK_CHARGES', 'Bank/Wire Charges'),
        ('HANDLING', 'Handling Fee'),
        ('INSPECTION', 'Inspection Fee'),
        ('OTHER', 'Other')
    ]
    
    import_order = models.ForeignKey(ImportOrder, on_delete=models.CASCADE, related_name='expenses')
    
    expense_type = models.CharField(max_length=50, choices=EXPENSE_TYPES)
    description = models.CharField(max_length=200)
    
    # Amount
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='USD')
    exchange_rate = models.DecimalField(max_digits=10, decimal_places=4, default=1)
    amount_in_local = models.DecimalField(max_digits=10, decimal_places=2)
    
    # Reference
    receipt_number = models.CharField(max_length=50, blank=True)
    date_incurred = models.DateField(default=timezone.now)
    
    # Documents
    receipt_file = models.FileField(upload_to='expense_receipts/', null=True, blank=True)
    
    # Payment tracking
    paid = models.BooleanField(default=False)
    payment_date = models.DateField(null=True, blank=True)
    
    created_date = models.DateTimeField(auto_now_add=True)
    
    def save(self, *args, **kwargs):
        # Smart exchange rate and local amount calculation

        # If expense currency matches order currency, use order's exchange rate
        if self.currency == self.import_order.currency:
            self.exchange_rate = self.import_order.exchange_rate
        # If expense is in USD (base currency), exchange rate should be 1.0
        elif self.currency == 'USD':
            self.exchange_rate = Decimal('1.0')
        # Otherwise, keep the manually entered exchange rate

        # Calculate local amount
        self.amount_in_local = self.amount * self.exchange_rate

        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"{self.expense_type} - {self.amount} {self.currency}"

class ImportOrderItem(models.Model):
    """Links inventory items to import orders with cost allocation"""
    
    import_order = models.ForeignKey(ImportOrder, on_delete=models.CASCADE, related_name='items')
    
    # Can link to existing product OR create new one
    inventory_item = models.ForeignKey(Inventory, on_delete=models.CASCADE, related_name='import_history', 
                                      null=True, blank=True)
    
    # Fields for creating NEW products (used if inventory_item is None)
    is_new_product = models.BooleanField(default=False, help_text="Check if this is a new product to be created")
    product_name = models.CharField(max_length=200, blank=True)
    product_category = models.ForeignKey('Inventory_category', on_delete=models.SET_NULL, null=True, blank=True,
                                        related_name='import_items')
    product_description = models.TextField(blank=True)
    product_label = models.CharField(max_length=50, blank=True)
    product_size = models.CharField(max_length=20, blank=True)
    product_weight = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    
    # Order details
    quantity = models.IntegerField()
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2)
    allocated_expenses = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # Price tracking (for comparison before/after allocation)
    old_selling_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True,
                                           help_text="Original selling price before allocation")

    # Received tracking
    quantity_received = models.IntegerField(default=0, help_text="Quantity actually received")
    is_received = models.BooleanField(default=False)
    received_date = models.DateField(null=True, blank=True)

    # Per-line routing: a single trip can supply both shops. NULL means the
    # receiving user picks at goods-in time.
    destination_shop = models.ForeignKey(
        'Shop', on_delete=models.PROTECT, null=True, blank=True,
        related_name='inbound_items',
        help_text="Which shop this line's stock is destined for when goods are received.",
    )

    # Optional: specific markup for this item
    markup_percentage = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    
    created_date = models.DateTimeField(auto_now_add=True)
    
    @property
    def total_cost(self):
        return self.unit_cost * self.quantity
    
    @property
    def landed_cost_per_unit(self):
        """Final cost per item including allocated expenses"""
        if self.quantity > 0:
            return self.unit_cost + (self.allocated_expenses / self.quantity)
        return self.unit_cost
    
    @property
    def suggested_selling_price(self):
        """Auto-calculate selling price with markup"""
        if self.markup_percentage:
            markup = self.markup_percentage / 100
        else:
            # Use category default or system default
            if self.inventory_item and hasattr(self.inventory_item, 'category') and self.inventory_item.category:
                markup = self.inventory_item.category.default_markup / 100
            elif self.product_category:
                markup = self.product_category.default_markup / 100
            else:
                # Use site settings default markup
                settings = SiteSettings.get_settings()
                markup = settings.default_markup_percent / 100

        return self.landed_cost_per_unit * (1 + markup)
    
    def create_inventory_item(self):
        """Create inventory item from import order item if it's a new product"""
        if not self.is_new_product or self.inventory_item:
            return self.inventory_item
        
        if not self.product_name:
            raise ValueError("Product name is required to create new inventory item")
        
        # Create the inventory item
        inventory_item = Inventory.objects.create(
            name=self.product_name,
            category=self.product_category,
            description=self.product_description,
            label=self.product_label or self.product_name[:50],
            size=self.product_size or '0',
            weight=self.product_weight,
            purchase_price=self.landed_cost_per_unit,
            selling_price=self.suggested_selling_price,
            quantity_in_Stock=0,  # Will be updated when goods are received
            bought_from=self.import_order.supplier.name,
            on_sale=True,
            source_import_order=self.import_order
        )
        
        # Link back to this import order item
        self.inventory_item = inventory_item
        self.save()
        
        return inventory_item
    
    def receive_goods(self, quantity_received=None, update_stock=True, update_selling_price=None):
        """
        Mark goods as received and optionally update stock

        Args:
            quantity_received: Quantity to receive (defaults to ordered quantity)
            update_stock: Whether to update stock levels
            update_selling_price: Optional bool to control selling price update
                                 - None (default): Auto-update for NEW products only
                                 - True: Force update selling price
                                 - False: Never update selling price
        """
        if quantity_received is None:
            quantity_received = self.quantity

        self.quantity_received = quantity_received
        self.is_received = True
        self.received_date = timezone.now().date()

        # Determine if this is a new product being created
        is_new_product_creation = self.is_new_product and not self.inventory_item

        # Create inventory item if it's a new product
        if is_new_product_creation:
            self.create_inventory_item()

        # Update stock if requested
        if update_stock and self.inventory_item:
            self.inventory_item.quantity_in_Stock += quantity_received

            # SMART PRICING LOGIC (Option B):
            # Always update purchase price to landed cost
            self.inventory_item.purchase_price = self.landed_cost_per_unit

            # Selling price update logic:
            if update_selling_price is True:
                # Explicitly requested to update
                self.inventory_item.selling_price = self.suggested_selling_price
            elif update_selling_price is False:
                # Explicitly requested NOT to update
                pass  # Keep existing selling price
            elif update_selling_price is None:
                # Default behavior: Only update for NEW products
                if is_new_product_creation:
                    self.inventory_item.selling_price = self.suggested_selling_price
                # For existing products, keep current selling price
                # Suggested price is available via self.suggested_selling_price property

            self.inventory_item.save()

            # Create stock movement
            StockMovement.objects.create(
                inventory_item=self.inventory_item,
                movement_type='IN',
                quantity=quantity_received,
                reason=f'Import Order {self.import_order.order_number} received'
            )

            # Post to GL: Dr Inventory, Cr Accounts Payable
            # Import the function here to avoid circular imports
            try:
                from accounting.utils import post_inventory_receipt
                post_inventory_receipt(self, user=None)
            except Exception as e:
                # Log but don't fail the receipt if GL posting fails
                print(f"[IMPORT] Warning: GL posting failed for item {self.id}: {e}")

        self.save()
    
    def __str__(self):
        if self.inventory_item:
            return f"{self.quantity}x {self.inventory_item.name}"
        elif self.product_name:
            return f"{self.quantity}x {self.product_name} (New)"
        return f"Import Order Item #{self.id}"

# ==================== BASIC ACCOUNTING AND CUSTOMER CREDIT/LAYBY ====================

class Customer(models.Model):
    STATUS_CHOICES = [
        ('ACTIVE', 'Active'),
        ('SUSPENDED', 'Suspended'),
        ('INACTIVE', 'Inactive'),
    ]

    name = models.CharField(max_length=200)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=50, blank=True)
    address = models.TextField(blank=True)

    # Credit profile (for on-account sales)
    credit_limit = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    current_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0,
                                         help_text="Outstanding A/R balance")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='ACTIVE')
    
    # Loyalty and communication preferences
    opt_in_for_emails = models.BooleanField(default=False, help_text="Customer agreed to receive email invoices")
    purchase_count = models.IntegerField(default=0, help_text="Total number of purchases for loyalty tracking")

    created_date = models.DateTimeField(auto_now_add=True)
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name




# ==================== SALES INVOICES FOR CUSTOMER RECEIPTS ====================

class SalesInvoice(models.Model):
    """Customer-facing invoices for sales transactions"""
    
    invoice_number = models.CharField(max_length=50, unique=True, editable=False)
    invoice_date = models.DateTimeField(default=timezone.now)
    
    # Customer is optional for cash sales but required for credit/layby
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, null=True, blank=True, 
                                related_name='sales_invoices')
    
    # Totals
    subtotal = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=15, decimal_places=2)
    
    # Email tracking
    email_sent = models.BooleanField(default=False)
    email_sent_date = models.DateTimeField(null=True, blank=True)
    
    # Metadata
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, 
                                   related_name='invoices_created')
    created_date = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-invoice_date']
    
    def save(self, *args, **kwargs):
        if not self.invoice_number:
            # Auto-generate invoice number: INV-2025-0001
            year = self.invoice_date.year
            last_invoice = SalesInvoice.objects.filter(
                invoice_date__year=year
            ).order_by('-invoice_number').first()
            
            if last_invoice and last_invoice.invoice_number:
                try:
                    last_num = int(last_invoice.invoice_number.split('-')[-1])
                    new_num = last_num + 1
                except (ValueError, IndexError):
                    new_num = 1
            else:
                new_num = 1
            
            self.invoice_number = f"INV-{year}-{new_num:04d}"
        
        super().save(*args, **kwargs)
    
    def send_email(self):
        """Send invoice to customer via email if they opted in"""
        if not self.customer or not self.customer.opt_in_for_emails or not self.customer.email:
            return False
        
        from django.template.loader import render_to_string
        from django.core.mail import send_mail
        from django.conf import settings
        
        try:
            # Render email template
            context = {'invoice': self, 'items': self.items.all()}
            html_message = render_to_string('inventory/invoice_email.html', context)
            
            send_mail(
                subject=f'Invoice {self.invoice_number}',
                message=f'Please find your invoice {self.invoice_number} attached.',
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[self.customer.email],
                html_message=html_message,
                fail_silently=False,
            )
            
            self.email_sent = True
            self.email_sent_date = timezone.now()
            self.save(update_fields=['email_sent', 'email_sent_date'])
            return True
        except Exception as e:
            print(f"Error sending email: {e}")
            return False
    
    def __str__(self):
        customer_name = self.customer.name if self.customer else "Walk-in Customer"
        return f"{self.invoice_number} - {customer_name}"


class SalesInvoiceItem(models.Model):
    """Line items for sales invoices"""
    
    invoice = models.ForeignKey(SalesInvoice, on_delete=models.CASCADE, related_name='items')
    sale = models.ForeignKey(Sales, on_delete=models.SET_NULL, null=True, blank=True)
    
    # Item details (stored for historical record)
    product_name = models.CharField(max_length=200)
    product_code = models.CharField(max_length=20, blank=True)
    quantity = models.IntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    line_total = models.DecimalField(max_digits=15, decimal_places=2)
    
    def save(self, *args, **kwargs):
        # Auto-calculate line total
        if not self.line_total:
            discounted_price = self.unit_price * (1 - self.discount_percent / 100)
            self.line_total = discounted_price * self.quantity
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"{self.quantity}x {self.product_name}"


# ============================================================
# Daily Z-Report (cash-up) — one record per shop per trading day
# ============================================================

class DailyCashUp(models.Model):
    """Snapshot of a shop's trading activity for one calendar day.

    Created when a manager "closes the day". After closure, the system
    refuses further SalesTickets for that shop+date combination.
    """
    shop = models.ForeignKey(
        'Shop', on_delete=models.PROTECT, related_name='daily_cashups',
    )
    date = models.DateField(db_index=True)

    # Z-number: sequential per shop, never reused.
    z_number = models.PositiveIntegerField()

    # Aggregated sales metrics
    ticket_count = models.PositiveIntegerField(default=0)
    gross_sales = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0'))
    discount_total = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0'))
    vat_total = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0'))
    net_sales = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0'))

    # Tender breakdown (cash_total = what should be in drawer)
    cash_total = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0'))
    ecocash_total = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0'))
    bank_transfer_total = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0'))
    card_total = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0'))

    # Cash count reconciliation
    counted_cash = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True,
        help_text='Physical cash counted in the drawer at close',
    )
    cash_variance = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True,
        help_text='counted_cash − cash_total; negative = shortage',
    )

    # Cashier breakdown stored as JSON: [{cashier_id, name, ticket_count, total}, ...]
    cashier_summary = models.JSONField(default=list, blank=True)

    notes = models.TextField(blank=True)
    closed_by = models.ForeignKey(
        'auth.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='daily_cashups_closed',
    )
    closed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('shop', 'date')]
        ordering = ['-date', 'shop']
        verbose_name = 'Daily Cash-Up'
        verbose_name_plural = 'Daily Cash-Ups'

    def __str__(self):
        return f"Z{self.z_number:05d} — {self.shop.code} {self.date}"

    @classmethod
    def next_z_number(cls, shop):
        last = cls.objects.filter(shop=shop).aggregate(m=models.Max('z_number'))['m']
        return (last or 0) + 1

    @classmethod
    def is_day_closed(cls, shop, date):
        return cls.objects.filter(shop=shop, date=date).exists()

