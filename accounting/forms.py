from django import forms
from django.forms import ModelForm
from .models import (
    GLAccount, JournalEntry, JournalLine, ARInvoice, ARPayment,
    LaybyPlan, LaybyItem, LaybyPayment, CashbookEntry, BankReconciliation
)

# ==================== TAILWIND CSS CLASSES ====================
TW_INPUT = 'w-full px-4 py-2.5 bg-gray-50 border border-gray-300 rounded-xl text-gray-900 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-colors'
TW_SELECT = TW_INPUT
TW_TEXTAREA = TW_INPUT + ' resize-y'
TW_CHECKBOX = 'w-4 h-4 text-blue-600 bg-gray-100 border-gray-300 rounded focus:ring-blue-500 focus:ring-2'


def apply_tailwind(form_instance):
    """Apply Tailwind CSS classes to all form fields."""
    for field_name, field in form_instance.fields.items():
        widget = field.widget
        if isinstance(widget, forms.CheckboxInput):
            widget.attrs['class'] = TW_CHECKBOX
        elif isinstance(widget, (forms.Select, forms.RadioSelect)):
            widget.attrs['class'] = TW_SELECT
        elif isinstance(widget, forms.Textarea):
            widget.attrs['class'] = TW_TEXTAREA
        else:
            widget.attrs['class'] = TW_INPUT


# ==================== GENERAL LEDGER FORMS ====================

class GLAccountForm(ModelForm):
    class Meta:
        model = GLAccount
        fields = ['code', 'name', 'type', 'is_active']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_tailwind(self)

class JournalEntryForm(ModelForm):
    class Meta:
        model = JournalEntry
        fields = ['entry_date', 'memo', 'reference']
        widgets = {
            'entry_date': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_tailwind(self)

class JournalLineForm(ModelForm):
    class Meta:
        model = JournalLine
        fields = ['account', 'description', 'debit', 'credit']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_tailwind(self)

# ==================== ACCOUNTS RECEIVABLE FORMS ====================

class ARInvoiceForm(ModelForm):
    class Meta:
        model = ARInvoice
        fields = ['customer', 'invoice_number', 'invoice_date', 'due_date', 'total_amount']
        widgets = {
            'invoice_date': forms.DateInput(attrs={'type': 'date'}),
            'due_date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_tailwind(self)

class ARPaymentFormSimple(ModelForm):
    class Meta:
        model = ARPayment
        fields = ['invoice', 'payment_date', 'amount', 'method', 'reference']
        widgets = {
            'payment_date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_tailwind(self)

    def clean(self):
        cleaned_data = super().clean()
        invoice = cleaned_data.get('invoice')
        amount = cleaned_data.get('amount')

        if invoice and amount:
            if amount > invoice.outstanding_amount:
                raise forms.ValidationError(
                    f'Payment amount (${amount}) exceeds outstanding balance (${invoice.outstanding_amount}). '
                    f'Please enter an amount equal to or less than ${invoice.outstanding_amount}.'
                )
            if amount <= 0:
                raise forms.ValidationError('Payment amount must be greater than zero.')

        return cleaned_data

# ==================== LAYBY FORMS ====================

class LaybyPlanForm(ModelForm):
    class Meta:
        model = LaybyPlan
        fields = ['customer', 'deposit_amount', 'due_date']
        widgets = {
            'due_date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_tailwind(self)

class LaybyItemForm(ModelForm):
    class Meta:
        model = LaybyItem
        fields = ['inventory_item', 'quantity', 'unit_price']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_tailwind(self)

class LaybyPaymentFormSimple(ModelForm):
    class Meta:
        model = LaybyPayment
        fields = ['plan', 'payment_date', 'amount', 'reference']
        widgets = {
            'payment_date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_tailwind(self)

    def clean(self):
        cleaned_data = super().clean()
        plan = cleaned_data.get('plan')
        amount = cleaned_data.get('amount')

        if plan and amount:
            remaining = plan.total_price - plan.amount_paid
            if amount > remaining:
                raise forms.ValidationError(
                    f'Payment amount (${amount}) exceeds remaining balance (${remaining}). '
                    f'Please enter an amount equal to or less than ${remaining}.'
                )
            if amount <= 0:
                raise forms.ValidationError('Payment amount must be greater than zero.')

        return cleaned_data

# ==================== CASHBOOK FORMS ====================

class CashbookEntryForm(ModelForm):
    class Meta:
        model = CashbookEntry
        fields = ['date', 'reference', 'description', 'category', 'receipt_amount', 'payment_amount']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_tailwind(self)

class BankReconciliationForm(ModelForm):
    class Meta:
        model = BankReconciliation
        fields = ['month', 'opening_balance', 'closing_balance', 'bank_statement_balance', 'notes']
        widgets = {
            'month': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_tailwind(self)

# ==================== UTILITY FORMS ====================

class DateRangeForm(forms.Form):
    start_date = forms.DateField(required=False, widget=forms.TextInput(attrs={'type': 'date'}))
    end_date = forms.DateField(required=False, widget=forms.TextInput(attrs={'type': 'date'}))

    def __init__(self, *args, **kwargs):
        super(DateRangeForm, self).__init__(*args, **kwargs)
        apply_tailwind(self)