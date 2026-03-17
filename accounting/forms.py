from django import forms
from django.forms import ModelForm
from .models import (
    GLAccount, JournalEntry, JournalLine, ARInvoice, ARPayment,
    LaybyPlan, LaybyItem, LaybyPayment, CashbookEntry, BankReconciliation
)

# ==================== GENERAL LEDGER FORMS ====================

class GLAccountForm(ModelForm):
    class Meta:
        model = GLAccount
        fields = ['code', 'name', 'type', 'is_active']

class JournalEntryForm(ModelForm):
    class Meta:
        model = JournalEntry
        fields = ['entry_date', 'memo', 'reference']
        widgets = {
            'entry_date': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        }

class JournalLineForm(ModelForm):
    class Meta:
        model = JournalLine
        fields = ['account', 'description', 'debit', 'credit']

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
        for f in self.fields.values():
            f.widget.attrs.update({'class': 'form-control'})

class ARPaymentFormSimple(ModelForm):
    class Meta:
        model = ARPayment
        fields = ['invoice', 'payment_date', 'amount', 'method', 'reference']
        widgets = {
            'payment_date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values():
            f.widget.attrs.update({'class': 'form-control'})

    def clean(self):
        cleaned_data = super().clean()
        invoice = cleaned_data.get('invoice')
        amount = cleaned_data.get('amount')

        if invoice and amount:
            # Check for overpayment
            if amount > invoice.outstanding_amount:
                raise forms.ValidationError(
                    f'Payment amount (${amount}) exceeds outstanding balance (${invoice.outstanding_amount}). '
                    f'Please enter an amount equal to or less than ${invoice.outstanding_amount}.'
                )

            # Check for zero or negative amount
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
        for f in self.fields.values():
            f.widget.attrs.update({'class': 'form-control'})

class LaybyItemForm(ModelForm):
    class Meta:
        model = LaybyItem
        fields = ['inventory_item', 'quantity', 'unit_price']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values():
            f.widget.attrs.update({'class': 'form-control'})

class LaybyPaymentFormSimple(ModelForm):
    class Meta:
        model = LaybyPayment
        fields = ['plan', 'payment_date', 'amount', 'reference']
        widgets = {
            'payment_date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values():
            f.widget.attrs.update({'class': 'form-control'})

    def clean(self):
        cleaned_data = super().clean()
        plan = cleaned_data.get('plan')
        amount = cleaned_data.get('amount')

        if plan and amount:
            # Calculate remaining balance
            remaining = plan.total_price - plan.amount_paid

            # Check for overpayment
            if amount > remaining:
                raise forms.ValidationError(
                    f'Payment amount (${amount}) exceeds remaining balance (${remaining}). '
                    f'Please enter an amount equal to or less than ${remaining}.'
                )

            # Check for zero or negative amount
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

class BankReconciliationForm(ModelForm):
    class Meta:
        model = BankReconciliation
        fields = ['month', 'opening_balance', 'closing_balance', 'bank_statement_balance', 'notes']
        widgets = {
            'month': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }

# ==================== UTILITY FORMS ====================

class DateRangeForm(forms.Form):
    start_date = forms.DateField(required=False, widget=forms.TextInput(attrs={'type': 'date'}))
    end_date = forms.DateField(required=False, widget=forms.TextInput(attrs={'type': 'date'}))

    def __init__(self, *args, **kwargs):
        super(DateRangeForm, self).__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'form-control'})