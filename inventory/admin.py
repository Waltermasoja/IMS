from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from django.utils.html import format_html
from .models import (
    Inventory, Inventory_category, Sales, Return, Damaged, StockMovement, missing_inventory,
    Supplier, ImportOrder, SupplierInvoice, InvoicePayment, ImportExpense, ImportOrderItem,
    UserProfile, Customer,
    SalesInvoice, SalesInvoiceItem,
    AttributeType, AttributeValue, ProductVariant
)

# ==================== EXISTING MODELS ====================

@admin.register(Inventory)
class InventoryAdmin(admin.ModelAdmin):
    list_display = ['image_preview', 'name', 'product_code', 'category', 'quantity_in_Stock', 'purchase_price', 'selling_price', 'on_sale']
    list_filter = ['category', 'on_sale', 'created_date']
    search_fields = ['name', 'description', 'label', 'product_code']
    readonly_fields = ['image_display', 'created_date', 'last_updated']

    fieldsets = (
        ('Product Image', {
            'fields': ('image', 'image_display')
        }),
        ('Basic Information', {
            'fields': ('category', 'bought_from', 'name', 'product_code', 'description')
        }),
        ('Details', {
            'fields': ('label', 'size', 'weight')
        }),
        ('Pricing & Stock', {
            'fields': ('purchase_price', 'selling_price', 'quantity_in_Stock', 'on_sale')
        }),
        ('Stock Control', {
            'fields': ('reorder_point', 'lead_time_days')
        }),
        ('Metadata', {
            'fields': ('created_date', 'last_updated', 'last_sale_date'),
            'classes': ('collapse',)
        })
    )

    def image_preview(self, obj):
        """Small thumbnail for list view"""
        if obj.thumbnail:
            return format_html(
                '<img src="{}" style="width: 50px; height: 50px; object-fit: cover; border-radius: 5px;" />',
                obj.thumbnail.url
            )
        return format_html('<div style="width: 50px; height: 50px; background: #f0f0f0; border-radius: 5px; display: flex; align-items: center; justify-content: center; color: #999;">📦</div>')
    image_preview.short_description = 'Image'

    def image_display(self, obj):
        """Larger image for detail view"""
        if obj.image:
            return format_html(
                '<img src="{}" style="max-width: 400px; max-height: 400px; object-fit: contain; border-radius: 10px; box-shadow: 0 2px 8px rgba(0,0,0,0.1);" />',
                obj.image.url
            )
        return format_html('<p style="color: #999;">No image uploaded</p>')
    image_display.short_description = 'Current Image'

@admin.register(Inventory_category)
class InventoryCategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'default_markup', 'date_created']
    search_fields = ['name']

@admin.register(Sales)
class SalesAdmin(admin.ModelAdmin):
    list_display = ['inventory_item', 'quantity_sold', 'sale_price', 'total_amount', 'sale_date']
    list_filter = ['sale_date']
    search_fields = ['inventory_item__name', 'receipt_number']

@admin.register(Return)
class ReturnAdmin(admin.ModelAdmin):
    list_display = ['inventory_item', 'quantity_returned', 'return_date', 'reason']
    list_filter = ['return_date']
    search_fields = ['inventory_item__name', 'receipt_number']

@admin.register(Damaged)
class DamagedAdmin(admin.ModelAdmin):
    list_display = ['inventory_item', 'quantity_damaged', 'damage_description']
    search_fields = ['inventory_item__name']

@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ['inventory_item', 'movement_type', 'quantity', 'reason', 'stock_date']
    list_filter = ['movement_type', 'stock_date']
    search_fields = ['inventory_item__name', 'reason']

@admin.register(missing_inventory)
class MissingInventoryAdmin(admin.ModelAdmin):
    list_display = ['inventory_item', 'quantity_missing', 'missing_date', 'reason']
    list_filter = ['missing_date']
    search_fields = ['inventory_item__name']

# ==================== IMPORT ORDER SYSTEM ====================

@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ['name', 'country', 'contact_person', 'email', 'payment_terms', 'is_active']
    list_filter = ['country', 'currency_preference', 'is_active', 'created_date']
    search_fields = ['name', 'contact_person', 'email']
    readonly_fields = ['total_orders', 'total_spent', 'created_date', 'last_updated']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'country', 'contact_person', 'email', 'phone', 'is_active')
        }),
        ('Financial', {
            'fields': ('payment_terms', 'currency_preference')
        }),
        ('Address', {
            'fields': ('address',)
        }),
        ('Statistics', {
            'fields': ('total_orders', 'total_spent', 'created_date', 'last_updated'),
            'classes': ('collapse',)
        })
    )

class ImportOrderItemInline(admin.TabularInline):
    model = ImportOrderItem
    extra = 1
    readonly_fields = ['allocated_expenses']

class ImportExpenseInline(admin.TabularInline):
    model = ImportExpense
    extra = 1
    readonly_fields = ['amount_in_local']

@admin.register(ImportOrder)
class ImportOrderAdmin(admin.ModelAdmin):
    list_display = ['order_number', 'supplier', 'status', 'order_date', 'total_landed_cost', 'allocation_completed']
    list_filter = ['status', 'allocation_method', 'allocation_completed', 'order_date']
    search_fields = ['order_number', 'supplier__name', 'reference_number']
    readonly_fields = ['order_number', 'total_expenses', 'total_landed_cost', 'total_items_count', 'payment_status', 'created_date', 'last_updated']
    
    inlines = [ImportOrderItemInline, ImportExpenseInline]
    
    fieldsets = (
        ('Order Information', {
            'fields': ('order_number', 'supplier', 'reference_number', 'status')
        }),
        ('Dates', {
            'fields': ('order_date', 'expected_arrival', 'actual_arrival')
        }),
        ('Financial', {
            'fields': ('currency', 'exchange_rate', 'goods_cost')
        }),
        ('Allocation', {
            'fields': ('allocation_method', 'allocation_completed', 'allocation_date')
        }),
        ('Summary', {
            'fields': ('total_expenses', 'total_landed_cost', 'total_items_count', 'payment_status'),
            'classes': ('collapse',)
        }),
        ('Additional', {
            'fields': ('notes', 'created_by', 'created_date', 'last_updated'),
            'classes': ('collapse',)
        })
    )

@admin.register(ImportOrderItem)
class ImportOrderItemAdmin(admin.ModelAdmin):
    list_display = ['import_order', 'inventory_item', 'quantity', 'unit_cost', 'allocated_expenses', 'landed_cost_per_unit']
    list_filter = ['import_order__status', 'created_date']
    search_fields = ['import_order__order_number', 'inventory_item__name']
    readonly_fields = ['total_cost', 'landed_cost_per_unit', 'suggested_selling_price']

@admin.register(ImportExpense)
class ImportExpenseAdmin(admin.ModelAdmin):
    list_display = ['import_order', 'expense_type', 'description', 'amount', 'currency', 'amount_in_local', 'paid']
    list_filter = ['expense_type', 'currency', 'paid', 'date_incurred']
    search_fields = ['import_order__order_number', 'description', 'receipt_number']
    readonly_fields = ['amount_in_local']

class InvoicePaymentInline(admin.TabularInline):
    model = InvoicePayment
    extra = 0
    readonly_fields = ['created_date']

@admin.register(SupplierInvoice)
class SupplierInvoiceAdmin(admin.ModelAdmin):
    list_display = ['invoice_number', 'import_order', 'total_amount', 'amount_paid', 'outstanding_amount', 'status', 'due_date']
    list_filter = ['status', 'currency', 'invoice_date', 'due_date']
    search_fields = ['invoice_number', 'import_order__order_number', 'import_order__supplier__name']
    readonly_fields = ['outstanding_amount', 'is_overdue', 'days_overdue', 'created_date', 'last_updated']
    
    inlines = [InvoicePaymentInline]
    
    fieldsets = (
        ('Invoice Information', {
            'fields': ('invoice_number', 'import_order', 'status')
        }),
        ('Financial', {
            'fields': ('currency', 'total_amount', 'amount_paid', 'outstanding_amount')
        }),
        ('Dates', {
            'fields': ('invoice_date', 'due_date', 'is_overdue', 'days_overdue')
        }),
        ('Documents', {
            'fields': ('invoice_file',)
        }),
        ('Additional', {
            'fields': ('notes', 'created_date', 'last_updated'),
            'classes': ('collapse',)
        })
    )

@admin.register(InvoicePayment)
class InvoicePaymentAdmin(admin.ModelAdmin):
    list_display = ['invoice', 'amount', 'payment_method', 'payment_date', 'reference_number']
    list_filter = ['payment_method', 'payment_date']
    search_fields = ['invoice__invoice_number', 'reference_number', 'bank_name']
    readonly_fields = ['created_date']

# ==================== USER MANAGEMENT ====================

class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    verbose_name_plural = 'User Profile'
    
    fieldsets = (
        ('Role & Permissions', {
            'fields': ('role',)
        }),
        ('POS Settings', {
            'fields': ('can_make_sales', 'can_process_returns', 'can_apply_discounts', 'max_discount_percent')
        }),
        ('Access Control', {
            'fields': ('can_view_reports', 'can_manage_inventory', 'can_manage_suppliers', 'can_manage_users')
        })
    )

class UserAdmin(BaseUserAdmin):
    inlines = (UserProfileInline,)
    
    def get_inline_instances(self, request, obj=None):
        if not obj:
            return list()
        return super(UserAdmin, self).get_inline_instances(request, obj)

# Re-register UserAdmin
admin.site.unregister(User)
admin.site.register(User, UserAdmin)

@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'role', 'can_make_sales', 'can_view_reports', 'max_discount_percent']
    list_filter = ['role', 'can_make_sales', 'can_view_reports', 'can_manage_inventory']
    search_fields = ['user__username', 'user__first_name', 'user__last_name']
    readonly_fields = ['created_date', 'last_updated']
    
    fieldsets = (
        ('User & Role', {
            'fields': ('user', 'role')
        }),
        ('POS Permissions', {
            'fields': ('can_make_sales', 'can_process_returns', 'can_apply_discounts', 'max_discount_percent')
        }),
        ('System Access', {
            'fields': ('can_view_reports', 'can_manage_inventory', 'can_manage_suppliers', 'can_manage_users')
        }),
        ('Metadata', {
            'fields': ('created_date', 'last_updated'),
            'classes': ('collapse',)
        })
    )

# ==================== ACCOUNTING & CREDIT/LAYBY ====================

@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ['name', 'phone', 'email', 'purchase_count', 'opt_in_for_emails', 'credit_limit', 'current_balance', 'status']
    list_filter = ['status', 'opt_in_for_emails', 'created_date']
    search_fields = ['name', 'phone', 'email']
    readonly_fields = ['purchase_count', 'created_date', 'last_updated']


# ==================== SALES INVOICES ====================

class SalesInvoiceItemInline(admin.TabularInline):
    model = SalesInvoiceItem
    extra = 0
    readonly_fields = ['line_total']

@admin.register(SalesInvoice)
class SalesInvoiceAdmin(admin.ModelAdmin):
    list_display = ['invoice_number', 'customer', 'total_amount', 'email_sent', 'invoice_date', 'created_by']
    list_filter = ['email_sent', 'invoice_date', 'created_date']
    search_fields = ['invoice_number', 'customer__name', 'customer__email']
    readonly_fields = ['invoice_number', 'email_sent_date', 'created_date']
    
    inlines = [SalesInvoiceItemInline]
    
    fieldsets = (
        ('Invoice Information', {
            'fields': ('invoice_number', 'customer', 'invoice_date')
        }),
        ('Amounts', {
            'fields': ('subtotal', 'tax_amount', 'discount_amount', 'total_amount')
        }),
        ('Email Status', {
            'fields': ('email_sent', 'email_sent_date')
        }),
        ('Additional', {
            'fields': ('notes', 'created_by', 'created_date'),
            'classes': ('collapse',)
        })
    )

@admin.register(SalesInvoiceItem)
class SalesInvoiceItemAdmin(admin.ModelAdmin):
    list_display = ['invoice', 'product_name', 'quantity', 'unit_price', 'discount_percent', 'line_total']
    list_filter = ['invoice__invoice_date']
    search_fields = ['invoice__invoice_number', 'product_name', 'product_code']
    readonly_fields = ['line_total']

# ==================== PRODUCT VARIANTS ====================

class AttributeValueInline(admin.TabularInline):
    model = AttributeValue
    extra = 1
    fields = ['value', 'display_value', 'color_code', 'display_order', 'is_active']
    ordering = ['display_order', 'value']

@admin.register(AttributeType)
class AttributeTypeAdmin(admin.ModelAdmin):
    list_display = ['name', 'display_name', 'display_order', 'is_active', 'values_count', 'created_date']
    list_filter = ['is_active', 'created_date']
    search_fields = ['name', 'display_name']
    ordering = ['display_order', 'name']
    inlines = [AttributeValueInline]
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'display_name', 'display_order', 'is_active')
        }),
        ('Metadata', {
            'fields': ('created_date',),
            'classes': ('collapse',)
        })
    )
    readonly_fields = ['created_date']
    
    def values_count(self, obj):
        return obj.values.count()
    values_count.short_description = 'Values'

@admin.register(AttributeValue)
class AttributeValueAdmin(admin.ModelAdmin):
    list_display = ['attribute_type', 'value', 'display_value', 'color_code', 'display_order', 'is_active']
    list_filter = ['attribute_type', 'is_active', 'attribute_type__is_active']
    search_fields = ['value', 'display_value', 'attribute_type__name']
    ordering = ['attribute_type', 'display_order', 'value']
    
    fieldsets = (
        ('Value Information', {
            'fields': ('attribute_type', 'value', 'display_value', 'color_code', 'display_order', 'is_active')
        }),
    )

@admin.register(ProductVariant)
class ProductVariantAdmin(admin.ModelAdmin):
    list_display = ['sku', 'product', 'attribute_values_display', 'quantity_in_stock', 'selling_price', 'is_active']
    list_filter = ['is_active', 'product__category', 'created_date']
    search_fields = ['sku', 'product__name', 'product__product_code']
    filter_horizontal = ['attribute_values']
    readonly_fields = ['created_date', 'last_updated']
    
    fieldsets = (
        ('Product & SKU', {
            'fields': ('product', 'sku', 'is_active')
        }),
        ('Pricing', {
            'fields': ('purchase_price', 'selling_price'),
            'description': 'Leave blank to use product default prices'
        }),
        ('Stock', {
            'fields': ('quantity_in_stock', 'reorder_point')
        }),
        ('Attributes', {
            'fields': ('attribute_values',)
        }),
        ('Metadata', {
            'fields': ('created_date', 'last_updated'),
            'classes': ('collapse',)
        })
    )
    
    def attribute_values_display(self, obj):
        """Display attribute values in a readable format"""
        values = obj.attribute_values.select_related('attribute_type').order_by('attribute_type__display_order', 'display_order')
        return ', '.join([f"{v.attribute_type.display_name}: {v.label}" for v in values])
    attribute_values_display.short_description = 'Attributes'

# Customize admin site header
admin.site.site_header = "Inventory Management System"
admin.site.site_title = "IMS Admin"
admin.site.index_title = "Welcome to IMS Administration"
