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