from django import forms
from django.forms import ModelForm, inlineformset_factory
from .models import (
    Inventory, Return, Damaged, Sales, Inventory_category,
    Supplier, ImportOrder, SupplierInvoice, InvoicePayment, 
    ImportExpense, ImportOrderItem, Customer
)

from .utils import get_exchange_rate, get_common_expenses_for_country
from decimal import Decimal

class AddInventoryForm(ModelForm):
    category = forms.ModelChoiceField(
        queryset=Inventory_category.objects.all(),
        empty_label="Select a category",
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
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
                'class': 'form-control',
                'accept': 'image/jpeg,image/jpg,image/png,image/webp'
            })
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

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
        self.fields['sale_price'].label = "Sale Price"
        self.fields['quantity_sold'].label = "Quantity to Sell"
        self.fields['discount_applied'].label = "Discount (%)"

class ReturnInventoryForm(forms.ModelForm):
    class Meta:
        model = Return
        fields = ['quantity_returned', 'reason']

class DamagedInventoryForm(forms.ModelForm):
    class Meta:
        model = Damaged
        fields = ['quantity_damaged', 'damage_description']

class LoginForm(forms.Form):
    username = forms.CharField()
    password = forms.CharField(widget=forms.PasswordInput)

class PeriodSummaryForm(forms.Form):
    start_date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))
    end_date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))

class DateRangeForm(forms.Form):
    start_date = forms.DateField(required=False, widget=forms.TextInput(attrs={'type': 'date'}))
    end_date = forms.DateField(required=False, widget=forms.TextInput(attrs={'type': 'date'}))

    def __init__(self, *args, **kwargs):
        super(DateRangeForm, self).__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'form-control'})

class Inventory_categoryForm(ModelForm):
    class Meta:
        model = Inventory_category
        fields = ['name', 'description', 'default_markup']

    def __init__(self, *args, **kwargs):
        super(Inventory_categoryForm, self).__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'form-control'})

        # Set help text for default_markup
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
    country = forms.ChoiceField(
        choices=COUNTRY_CHOICES,
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    payment_terms = forms.ChoiceField(
        choices=PAYMENT_TERMS_CHOICES,
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    currency_preference = forms.ChoiceField(
        choices=CURRENCY_CHOICES,
        widget=forms.Select(attrs={'class': 'form-control'})
    )

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
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'form-control'})

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
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'form-control'})
        
        # Auto-populate exchange rate when currency changes (via JavaScript)
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
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'form-control'})
        
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
        
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'form-control'})
        
        # Make date_incurred and receipt_number optional by default
        self.fields['date_incurred'].required = False
        self.fields['receipt_number'].required = False
        
        # Pre-populate currency and exchange rate from import order
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
    class Meta:
        model = SupplierInvoice
        fields = [
            'invoice_number', 'currency', 'total_amount', 
            'invoice_date', 'due_date', 'notes'
        ]
        widgets = {
            'invoice_date': forms.DateInput(attrs={'type': 'date'}),
            'due_date': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        import_order = kwargs.pop('import_order', None)
        super().__init__(*args, **kwargs)
        
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'form-control'})
        
        # Pre-populate from import order
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
        
        # Save invoice on the form for use in clean methods
        self.invoice = invoice
        
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'form-control'})
        
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
    allocation_method = forms.ChoiceField(
        choices=ImportOrder.ALLOCATION_METHODS,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    
    def __init__(self, *args, **kwargs):
        import_order = kwargs.pop('import_order', None)
        super().__init__(*args, **kwargs)
        
        if import_order and import_order.allocation_method == 'CUSTOM':
            # Add percentage fields for each item
            for item in import_order.items.all():
                field_name = f'item_{item.id}_percentage'
                self.fields[field_name] = forms.DecimalField(
                    label=f'{item.inventory_item.name} (%)',
                    max_digits=5,
                    decimal_places=2,
                    min_value=0,
                    max_value=100,
                    widget=forms.NumberInput(attrs={
                        'class': 'form-control',
                        'step': '0.01'
                    })
                )

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
        widget=forms.FileInput(attrs={'class': 'form-control', 'accept': '.csv'})
    )
    
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
    country = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    goods_value = forms.DecimalField(
        max_digits=15,
        decimal_places=2,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'})
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
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
        # Tailwind-friendly defaults
        base_cls = 'w-full border rounded-lg px-3 py-2'
        for f in self.fields.values():
            existing = f.widget.attrs.get('class', '')
            f.widget.attrs.update({'class': (existing + ' ' + base_cls).strip()})

        # Set help text and label for opt_in_for_emails
        self.fields['opt_in_for_emails'].help_text = 'Customer agrees to receive email invoices'
        self.fields['opt_in_for_emails'].label = 'Email opt-in for invoices'


class QuickCustomerForm(forms.ModelForm):
    """Quick form for adding customer during POS sale"""
    class Meta:
        model = Customer
        fields = ['name', 'phone', 'email']
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values():
            f.widget.attrs.update({'class': 'form-control'})
        
        self.fields['email'].required = False
        self.fields['phone'].required = False
