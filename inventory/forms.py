from django import forms
from django.forms import ModelForm, inlineformset_factory
from .models import (
    Inventory, Return, Damaged, Sales, Inventory_category,
    Supplier, ImportOrder, SupplierInvoice, InvoicePayment,
    ImportExpense, ImportOrderItem, Customer, SiteSettings,
    AttributeType, AttributeValue, ProductVariant
)

from .utils import get_exchange_rate, get_common_expenses_for_country
from decimal import Decimal


# ==================== TAILWIND CSS CLASSES ====================
TW_INPUT = 'w-full px-4 py-2.5 bg-gray-50 border border-gray-300 rounded-xl text-gray-900 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-colors'
TW_SELECT = TW_INPUT
TW_TEXTAREA = TW_INPUT + ' resize-y'
TW_FILE = 'w-full text-sm text-gray-500 file:mr-4 file:py-2.5 file:px-4 file:rounded-xl file:border-0 file:text-sm file:font-medium file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100 transition-colors'
TW_CHECKBOX = 'w-4 h-4 text-blue-600 bg-gray-100 border-gray-300 rounded focus:ring-blue-500 focus:ring-2'
TW_DATE = TW_INPUT


def apply_tailwind(form_instance):
    """Apply Tailwind CSS classes to all form fields."""
    for field_name, field in form_instance.fields.items():
        widget = field.widget
        if isinstance(widget, forms.CheckboxInput):
            widget.attrs['class'] = TW_CHECKBOX
        elif isinstance(widget, forms.FileInput):
            widget.attrs['class'] = TW_FILE
        elif isinstance(widget, (forms.Select, forms.RadioSelect)):
            widget.attrs['class'] = TW_SELECT
        elif isinstance(widget, forms.Textarea):
            widget.attrs['class'] = TW_TEXTAREA
        elif isinstance(widget, forms.CheckboxSelectMultiple):
            pass  # Don't override checkbox groups
        else:
            widget.attrs['class'] = TW_INPUT


# ==================== SITE SETTINGS FORM ====================

class SiteSettingsForm(ModelForm):
    """Form for editing site-wide settings with tabbed sections"""

    class Meta:
        model = SiteSettings
        exclude = ['created_date', 'last_updated', 'updated_by']
        widgets = {
            'company_address': forms.Textarea(attrs={'rows': 3}),
            'company_logo': forms.FileInput(attrs={'accept': 'image/*'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_tailwind(self)

        # Group fields by section for template organization
        self.company_fields = [
            'company_name', 'company_address', 'company_phone',
            'company_email', 'company_website', 'tax_registration_number', 'company_logo'
        ]
        self.financial_fields = [
            'default_currency', 'currency_symbol_position', 'decimal_places',
            'tax_rate', 'financial_year_start'
        ]
        self.credit_fields = [
            'default_credit_limit', 'default_payment_terms_days', 'credit_grace_period_days',
            'enable_interest_charges', 'interest_rate_monthly'
        ]
        self.layby_fields = [
            'layby_minimum_deposit_percent', 'layby_max_duration_days',
            'layby_cancellation_fee_percent'
        ]
        self.inventory_fields = [
            'low_stock_threshold', 'default_markup_percent',
            'allow_negative_stock', 'track_stock_movements'
        ]
        self.pos_fields = [
            'receipt_prefix', 'invoice_prefix', 'import_order_prefix', 'layby_prefix',
            'max_discount_percent', 'require_customer_for_sales', 'print_receipt_automatically'
        ]
        self.display_fields = [
            'date_format', 'time_format', 'items_per_page'
        ]

    def get_fields_by_section(self):
        """Return fields organized by section for template rendering"""
        return {
            'company': [(name, self[name]) for name in self.company_fields if name in self.fields],
            'financial': [(name, self[name]) for name in self.financial_fields if name in self.fields],
            'credit': [(name, self[name]) for name in self.credit_fields if name in self.fields],
            'layby': [(name, self[name]) for name in self.layby_fields if name in self.fields],
            'inventory': [(name, self[name]) for name in self.inventory_fields if name in self.fields],
            'pos': [(name, self[name]) for name in self.pos_fields if name in self.fields],
            'display': [(name, self[name]) for name in self.display_fields if name in self.fields],
        }

class AddInventoryForm(ModelForm):
    category = forms.ModelChoiceField(
        queryset=Inventory_category.objects.all(),
        empty_label="Select a category",
        required=False,
    )

    class Meta:
        model = Inventory
        fields = [
            'category',
            'bought_from',
            'name',
            'product_code',
            'purchase_price',
            'selling_price',
            'quantity_in_Stock',
            'description',
            'label',
            'size',
            'weight',
            'image',
            'on_sale',
            'reorder_point',
            'lead_time_days'
        ]
        widgets = {
            'image': forms.FileInput(attrs={
                'accept': 'image/jpeg,image/jpg,image/png,image/webp'
            })
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_tailwind(self)

        # Make fields optional
        self.fields['category'].required = False
        self.fields['bought_from'].required = False
        self.fields['purchase_price'].required = False
        self.fields['selling_price'].required = False
        self.fields['label'].required = False
        self.fields['size'].required = False
        self.fields['weight'].required = False

        self.fields['category'].help_text = '<a href="#" data-bs-toggle="modal" data-bs-target="#addCategoryModal">+ Add New Category</a>'
        self.fields['product_code'].help_text = 'Leave blank to auto-generate based on category'
        self.fields['product_code'].widget.attrs.update({'placeholder': 'e.g., SHI-0001 (auto-generated if empty)'})
        self.fields['reorder_point'].help_text = 'Minimum stock level before reordering'
        self.fields['lead_time_days'].help_text = 'Supplier lead time in days'
        self.fields['image'].help_text = 'Upload product image (max 5MB, auto-resized to 800x600px). Accepted formats: JPG, PNG, WebP'
        self.fields['size'].help_text = 'Size can be text (e.g., "Small", "Medium") or numeric (e.g., "10", "42")'

    def clean(self):
        cleaned_data = super().clean()
        purchase_price = cleaned_data.get('purchase_price')
        selling_price = cleaned_data.get('selling_price')
        quantity_in_Stock = cleaned_data.get('quantity_in_Stock')

        if purchase_price is not None and purchase_price < 0:
            self.add_error('purchase_price', 'Purchase price cannot be negative')

        if selling_price is not None and selling_price < 0:
            self.add_error('selling_price', 'Selling price cannot be negative')

        if quantity_in_Stock is not None and quantity_in_Stock < 0:
            self.add_error('quantity_in_Stock', 'Stock quantity cannot be negative')

        # Only validate selling price vs purchase price if both are provided and non-zero
        if selling_price and purchase_price and selling_price > 0 and purchase_price > 0:
            if selling_price < purchase_price:
                self.add_error('selling_price', 'Selling price cannot be less than purchase price')

        return cleaned_data

class UpdateInventoryForm(ModelForm):
    class Meta:
        model = Sales
        fields = ['quantity_sold', 'sale_price', 'discount_applied']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_tailwind(self)
        self.fields['sale_price'].label = "Sale Price"
        self.fields['quantity_sold'].label = "Quantity to Sell"
        self.fields['discount_applied'].label = "Discount (%)"

class ReturnInventoryForm(forms.ModelForm):
    class Meta:
        model = Return
        fields = ['quantity_returned', 'reason']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_tailwind(self)

class DamagedInventoryForm(forms.ModelForm):
    class Meta:
        model = Damaged
        fields = ['quantity_damaged', 'damage_description']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_tailwind(self)

class LoginForm(forms.Form):
    username = forms.CharField()
    password = forms.CharField(widget=forms.PasswordInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_tailwind(self)

class PeriodSummaryForm(forms.Form):
    start_date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))
    end_date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_tailwind(self)

class DateRangeForm(forms.Form):
    start_date = forms.DateField(required=False, widget=forms.TextInput(attrs={'type': 'date'}))
    end_date = forms.DateField(required=False, widget=forms.TextInput(attrs={'type': 'date'}))

    def __init__(self, *args, **kwargs):
        super(DateRangeForm, self).__init__(*args, **kwargs)
        apply_tailwind(self)

class Inventory_categoryForm(ModelForm):
    class Meta:
        model = Inventory_category
        fields = ['name', 'description', 'default_markup']

    def __init__(self, *args, **kwargs):
        super(Inventory_categoryForm, self).__init__(*args, **kwargs)
        apply_tailwind(self)
        self.fields['default_markup'].help_text = 'Default markup percentage for products in this category (e.g., 40 for 40%)'

# ==================== IMPORT ORDER & LANDED COST FORMS ====================

class SupplierForm(ModelForm):
    # Add country as a choice field
    COUNTRY_CHOICES = [
        ('China', 'China'),
        ('Turkey', 'Turkey'),
        ('South Africa', 'South Africa'),
        ('United Kingdom', 'United Kingdom'),
        ('United States', 'United States'),
        ('India', 'India'),
        ('Germany', 'Germany'),
        ('Italy', 'Italy'),
        ('France', 'France'),
        ('Spain', 'Spain'),
        ('Japan', 'Japan'),
        ('South Korea', 'South Korea'),
        ('Thailand', 'Thailand'),
        ('Vietnam', 'Vietnam'),
        ('Malaysia', 'Malaysia'),
        ('Indonesia', 'Indonesia'),
        ('UAE', 'United Arab Emirates'),
        ('Kenya', 'Kenya'),
        ('Zimbabwe', 'Zimbabwe'),
        ('Botswana', 'Botswana'),
        ('Zambia', 'Zambia'),
        ('Other', 'Other'),
    ]

    PAYMENT_TERMS_CHOICES = [
        ('', 'Select payment terms'),
        ('NET 7', 'NET 7 days'),
        ('NET 15', 'NET 15 days'),
        ('NET 30', 'NET 30 days'),
        ('NET 45', 'NET 45 days'),
        ('NET 60', 'NET 60 days'),
        ('NET 90', 'NET 90 days'),
        ('COD', 'Cash on Delivery'),
        ('PREPAID', 'Prepaid'),
        ('CIA', 'Cash in Advance'),
    ]

    CURRENCY_CHOICES = [
        ('USD', 'US Dollar'),
        ('TRY', 'Turkish Lira'),
        ('RMB', 'Renminbi'),
        ('ZAR', 'South African Rand'),
        ('GBP', 'British Pound'),
        ('CNY', 'Chinese Yuan'),
        ('EUR', 'Euro')
    ]
    country = forms.ChoiceField(choices=COUNTRY_CHOICES)
    payment_terms = forms.ChoiceField(choices=PAYMENT_TERMS_CHOICES)
    currency_preference = forms.ChoiceField(choices=CURRENCY_CHOICES)

    class Meta:
        model = Supplier
        fields = [
            'name', 'country', 'contact_person', 'email', 'phone',
            'payment_terms', 'currency_preference', 'address', 'is_active'
        ]
        widgets = {
            'address': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_tailwind(self)

class ImportOrderForm(ModelForm):
    class Meta:
        model = ImportOrder
        fields = [
            'supplier', 'reference_number', 'order_date', 'expected_arrival',
            'currency', 'exchange_rate', 'status', 'allocation_method', 'notes'
        ]
        widgets = {
            'order_date': forms.DateInput(attrs={'type': 'date'}),
            'expected_arrival': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_tailwind(self)
        self.fields['exchange_rate'].help_text = 'Will auto-populate based on current rates'

    def clean(self):
        cleaned_data = super().clean()
        order_date = cleaned_data.get('order_date')
        expected_arrival = cleaned_data.get('expected_arrival')
        
        if order_date and expected_arrival and expected_arrival < order_date:
            raise forms.ValidationError("Expected arrival cannot be before order date")
        
        return cleaned_data

class ImportOrderItemForm(ModelForm):
    class Meta:
        model = ImportOrderItem
        fields = ['inventory_item', 'quantity', 'unit_cost', 'markup_percentage']
        
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_tailwind(self)
        self.fields['markup_percentage'].help_text = 'Leave blank to use category default'

# Create inline formset for import order items
ImportOrderItemFormSet = inlineformset_factory(
    ImportOrder, 
    ImportOrderItem,
    form=ImportOrderItemForm,
    extra=0,  # Don't show extra forms by default - we'll handle it in the view
    min_num=1,
    validate_min=True,
    can_delete=True
)

class ImportExpenseForm(ModelForm):
    class Meta:
        model = ImportExpense
        fields = [
            'expense_type', 'description', 'amount', 'currency', 
            'exchange_rate', 'receipt_number', 'date_incurred', 'paid'
        ]
        widgets = {
            'date_incurred': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        import_order = kwargs.pop('import_order', None)
        super().__init__(*args, **kwargs)
        apply_tailwind(self)

        self.fields['date_incurred'].required = False
        self.fields['receipt_number'].required = False

        if import_order:
            self.fields['currency'].initial = import_order.currency
            self.fields['exchange_rate'].initial = import_order.exchange_rate
    
    def clean(self):
        cleaned_data = super().clean()
        paid = cleaned_data.get('paid')
        date_incurred = cleaned_data.get('date_incurred')
        receipt_number = cleaned_data.get('receipt_number')
        currency = cleaned_data.get('currency')
        exchange_rate = cleaned_data.get('exchange_rate')

        # Only require date_incurred and receipt_number if expense is marked as paid
        if paid:
            if not date_incurred:
                self.add_error('date_incurred', 'Date incurred is required when expense is marked as paid.')
            if not receipt_number:
                self.add_error('receipt_number', 'Receipt number is required when expense is marked as paid.')

        # Smart exchange rate handling:
        # If expense currency is USD (base currency), exchange rate should be 1.0
        if currency == 'USD' and exchange_rate and float(exchange_rate) != 1.0:
            cleaned_data['exchange_rate'] = 1.0

        return cleaned_data

# Create inline formset for import expenses
ImportExpenseFormSet = inlineformset_factory(
    ImportOrder,
    ImportExpense,
    form=ImportExpenseForm,
    extra=1,
    can_delete=True
)

class SupplierInvoiceForm(ModelForm):
    currency = forms.ChoiceField(
        choices=ImportOrder._meta.get_field('currency').choices,
    )
    status = forms.ChoiceField(
        choices=SupplierInvoice.INVOICE_STATUS,
        initial='PENDING',
    )

    class Meta:
        model = SupplierInvoice
        fields = [
            'invoice_number', 'currency', 'total_amount', 
            'invoice_date', 'due_date', 'status', 'notes'
        ]
        widgets = {
            'invoice_date': forms.DateInput(attrs={'type': 'date'}),
            'due_date': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        import_order = kwargs.pop('import_order', None)
        super().__init__(*args, **kwargs)
        apply_tailwind(self)

        if import_order:
            self.fields['currency'].initial = import_order.currency
            # Auto-calculate due date based on supplier payment terms
            if hasattr(import_order, 'supplier') and import_order.supplier.payment_terms:
                from .utils import calculate_due_date
                from django.utils import timezone
                invoice_date = timezone.now().date()
                due_date = calculate_due_date(invoice_date, import_order.supplier.payment_terms)
                self.fields['due_date'].initial = due_date

class InvoicePaymentForm(ModelForm):
    class Meta:
        model = InvoicePayment
        fields = [
            'payment_date', 'amount', 'payment_method', 
            'reference_number', 'bank_name', 'transaction_fee', 'notes'
        ]
        widgets = {
            'payment_date': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        invoice = kwargs.pop('invoice', None)
        super().__init__(*args, **kwargs)
        self.invoice = invoice
        apply_tailwind(self)
        
        # Set max amount to outstanding balance
        if self.invoice:
            max_amount = self.invoice.outstanding_amount
            self.fields['amount'].widget.attrs.update({
                'max': str(max_amount),
                'step': '0.01'
            })
            self.fields['amount'].help_text = f'Maximum: {max_amount}'

    def clean_amount(self):
        amount = self.cleaned_data.get('amount')
        if getattr(self, 'invoice', None) and amount:
            if amount > self.invoice.outstanding_amount:
                raise forms.ValidationError(
                    f"Payment amount cannot exceed outstanding balance of {self.invoice.outstanding_amount}"
                )
        return amount

class ExpenseAllocationForm(forms.Form):
    """Form for custom expense allocation"""
    allocation_method = forms.ChoiceField(choices=ImportOrder.ALLOCATION_METHODS)

    def __init__(self, *args, **kwargs):
        import_order = kwargs.pop('import_order', None)
        super().__init__(*args, **kwargs)

        if import_order and import_order.allocation_method == 'CUSTOM':
            for item in import_order.items.all():
                field_name = f'item_{item.id}_percentage'
                self.fields[field_name] = forms.DecimalField(
                    label=f'{item.inventory_item.name} (%)',
                    max_digits=5,
                    decimal_places=2,
                    min_value=0,
                    max_value=100,
                    widget=forms.NumberInput(attrs={'step': '0.01'})
                )
        apply_tailwind(self)

    def clean(self):
        cleaned_data = super().clean()
        allocation_method = cleaned_data.get('allocation_method')
        
        if allocation_method == 'CUSTOM':
            # Validate that percentages sum to 100
            total_percentage = Decimal('0')
            for field_name, value in cleaned_data.items():
                if field_name.startswith('item_') and field_name.endswith('_percentage'):
                    if value:
                        total_percentage += value
            
            if abs(total_percentage - Decimal('100')) > Decimal('0.01'):
                raise forms.ValidationError(
                    f"Percentages must sum to 100%. Current total: {total_percentage}%"
                )
        
        return cleaned_data

class BulkInventoryImportForm(forms.Form):
    """Form for bulk importing inventory items to an import order"""
    csv_file = forms.FileField(
        help_text="Upload CSV with columns: name, quantity, unit_cost, weight, category",
        widget=forms.FileInput(attrs={'accept': '.csv'})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_tailwind(self)
    
    def clean_csv_file(self):
        file = self.cleaned_data.get('csv_file')
        if file:
            if not file.name.endswith('.csv'):
                raise forms.ValidationError("File must be a CSV file")
            
            # Basic file size check (max 5MB)
            if file.size > 5 * 1024 * 1024:
                raise forms.ValidationError("File size must be less than 5MB")
        
        return file

class QuickExpenseForm(forms.Form):
    """Quick form to add common expenses based on country"""
    country = forms.CharField(max_length=100)
    goods_value = forms.DecimalField(
        max_digits=15,
        decimal_places=2,
        widget=forms.NumberInput(attrs={'step': '0.01'})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_tailwind(self)
        self.fields['country'].help_text = 'Enter supplier country to auto-generate common expenses'
        self.fields['goods_value'].help_text = 'Total value of goods for expense estimation'

# ==================== CUSTOMER FORMS ====================

class CustomerForm(ModelForm):
    class Meta:
        model = Customer
        fields = ['name', 'email', 'phone', 'address', 'credit_limit', 'status', 'opt_in_for_emails']
        widgets = {
            'address': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_tailwind(self)

        self.fields['opt_in_for_emails'].help_text = 'Customer agrees to receive email invoices'
        self.fields['opt_in_for_emails'].label = 'Email opt-in for invoices'

        if not self.instance.pk:
            try:
                settings = SiteSettings.get_settings()
                self.fields['credit_limit'].initial = settings.default_credit_limit
            except Exception:
                pass


class QuickCustomerForm(forms.ModelForm):
    """Quick form for adding customer during POS sale"""
    class Meta:
        model = Customer
        fields = ['name', 'phone', 'email']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_tailwind(self)
        self.fields['email'].required = False
        self.fields['phone'].required = False


# ==================== PRODUCT VARIANT FORMS ====================

class ProductWithVariantsForm(ModelForm):
    """
    Step 1: Basic product information for products with variants.
    Similar to AddInventoryForm but with variant-specific fields.
    """
    category = forms.ModelChoiceField(
        queryset=Inventory_category.objects.all(),
        empty_label="Select a category",
        required=False,
    )

    variant_attribute_types = forms.ModelMultipleChoiceField(
        queryset=AttributeType.objects.filter(is_active=True),
        widget=forms.CheckboxSelectMultiple(),
        required=True,
        help_text="Select which attributes this product will have variants for"
    )

    class Meta:
        model = Inventory
        fields = [
            'category',
            'name',
            'product_code',
            'description',
            'purchase_price',
            'selling_price',
            'weight',
            'image',
            'on_sale',
            'reorder_point',
        ]
        widgets = {
            'image': forms.FileInput(attrs={
                'accept': 'image/jpeg,image/jpg,image/png,image/webp'
            }),
            'description': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_tailwind(self)

        self.fields['product_code'].help_text = 'Leave blank to auto-generate'
        self.fields['purchase_price'].help_text = 'Default cost (can be overridden per variant)'
        self.fields['selling_price'].help_text = 'Default price (can be overridden per variant)'
        self.fields['reorder_point'].help_text = 'Default reorder point for variants'

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.has_variants = True
        instance.quantity_in_Stock = 0  # Stock is tracked at variant level
        if commit:
            instance.save()
            # Set the variant attribute types
            instance.variant_attributes.set(self.cleaned_data['variant_attribute_types'])
        return instance


class VariantAttributeSelectionForm(forms.Form):
    """
    Step 2: Select which attribute values to create variants for.
    Dynamically generates checkbox fields based on selected attribute types.
    At least one attribute must have selections, but not all are required.
    """

    def __init__(self, *args, attribute_types=None, **kwargs):
        super().__init__(*args, **kwargs)

        if attribute_types:
            for attr_type in attribute_types:
                # Create a checkbox field for each attribute value
                values = AttributeValue.objects.filter(
                    attribute_type=attr_type,
                    is_active=True
                ).order_by('display_order')

                self.fields[f'attr_{attr_type.id}'] = forms.ModelMultipleChoiceField(
                    queryset=values,
                    widget=forms.CheckboxSelectMultiple(),
                    required=False,
                    label=attr_type.display_name,
                    help_text=f"Select {attr_type.display_name.lower()} options (optional)"
                )

    def clean(self):
        """Ensure at least one attribute has selections."""
        cleaned_data = super().clean()

        # Check if at least one attribute field has selections
        has_any_selection = False
        for field_name, value in cleaned_data.items():
            if field_name.startswith('attr_') and value:
                has_any_selection = True
                break

        if not has_any_selection:
            raise forms.ValidationError(
                "Please select at least one option from any attribute type."
            )

        return cleaned_data

    def get_selected_values(self):
        """Returns dict of attribute_type_id -> list of selected AttributeValue objects"""
        result = {}
        for field_name, value in self.cleaned_data.items():
            if field_name.startswith('attr_') and value:  # Only include non-empty selections
                attr_type_id = int(field_name.replace('attr_', ''))
                result[attr_type_id] = list(value)
        return result


class ProductVariantForm(ModelForm):
    """Form for individual variant details (used in the grid)"""

    class Meta:
        model = ProductVariant
        fields = ['sku', 'purchase_price', 'selling_price', 'quantity_in_stock', 'reorder_point', 'is_active']
        widgets = {
            'purchase_price': forms.NumberInput(attrs={'step': '0.01'}),
            'selling_price': forms.NumberInput(attrs={'step': '0.01'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_tailwind(self)
        self.fields['sku'].required = False
        self.fields['purchase_price'].required = False
        self.fields['selling_price'].required = False


class BulkVariantForm(forms.Form):
    """Form for bulk editing variant properties"""

    set_purchase_price = forms.DecimalField(
        max_digits=10, decimal_places=2, required=False,
        widget=forms.NumberInput(attrs={'step': '0.01', 'placeholder': 'Set all costs'})
    )
    set_selling_price = forms.DecimalField(
        max_digits=10, decimal_places=2, required=False,
        widget=forms.NumberInput(attrs={'step': '0.01', 'placeholder': 'Set all prices'})
    )
    set_quantity = forms.IntegerField(
        required=False,
        widget=forms.NumberInput(attrs={'placeholder': 'Set all stock'})
    )
    set_reorder_point = forms.IntegerField(
        required=False,
        widget=forms.NumberInput(attrs={'placeholder': 'Set all reorder points'})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_tailwind(self)


class AddAttributeValueForm(forms.ModelForm):
    """Form for adding a custom attribute value (e.g., a new size or color)"""

    class Meta:
        model = AttributeValue
        fields = ['attribute_type', 'value', 'display_value', 'color_code']
        widgets = {
            'value': forms.TextInput(attrs={'placeholder': 'e.g., 4XL or Burgundy'}),
            'display_value': forms.TextInput(attrs={'placeholder': 'Display name (optional)'}),
            'color_code': forms.TextInput(attrs={'placeholder': '#FF0000'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_tailwind(self)
        self.fields['display_value'].required = False
        self.fields['color_code'].required = False
        self.fields['color_code'].help_text = 'Hex color code for color swatches (only for Color attribute)'
