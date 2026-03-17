from django import forms
from django.forms import ModelForm
from .models import Expense

class ExpenseForm(ModelForm):
    class Meta:
        model = Expense
        fields = ['date', 'category', 'description', 'amount', 'gl_account', 'payment_method', 'reference']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
        }
