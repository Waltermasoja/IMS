from django.forms import ModelForm
from .models import Inventory, Return, Damaged
from django import forms
from django.contrib.auth.forms import AuthenticationForm

class AddInventoryForm(ModelForm):
    class Meta:
        model = Inventory
        fields = ['name', 'cost', 'quantity_in_Stock', 'quantity_sold', 'description', 'label', 'size']

    def clean(self):
        cleaned_data = super().clean()
        quantity_in_stock = cleaned_data.get('quantity_in_Stock')
        quantity_sold = cleaned_data.get('quantity_sold')
        cost = cleaned_data.get('cost')

        if quantity_in_stock is not None and quantity_in_stock < 0:
            self.add_error('quantity_in_Stock', 'Quantity in stock cannot be negative')

        if quantity_sold is not None and quantity_sold < 0:
            self.add_error('quantity_sold', 'Quantity sold cannot be negative')

        if cost is not None and cost < 0:
            self.add_error('cost', 'Cost cannot be negative')

        if not cleaned_data.get('name'):
            self.add_error('name', 'Product name is required')

        return cleaned_data

class UpdateInventoryForm(ModelForm):
    class Meta:
        model = Inventory
        fields = ['name', 'cost', 'quantity_sold', 'sell', 'label', 'size']

    def clean(self):
        cleaned_data = super().clean()
        quantity_sold = cleaned_data.get('quantity_sold')
        cost = cleaned_data.get('cost')
        sell = cleaned_data.get('sell')

        if quantity_sold is not None and quantity_sold < 0:
            self.add_error('quantity_sold', 'Quantity sold cannot be negative')

        if cost is not None and cost < 0:
            self.add_error('cost', 'Cost cannot be negative')

        if sell is not None:
            if sell < 0:
                self.add_error('sell', 'Discount percentage cannot be negative')
            elif sell > 100:
                self.add_error('sell', 'Discount percentage cannot exceed 100%')

        return cleaned_data

class PeriodSummaryForm(forms.Form):
    PERIOD_CHOICES = [ 
        ('day','Day'),
        ('month','Month'),
        ('year','Year'),
    ]
    period = forms.ChoiceField(choices= PERIOD_CHOICES)

class DateRangeForm(forms.Form):
    start_date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))
    end_date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))

class ReturnInventoryForm(forms.ModelForm):
    class Meta:
        model = Return
        fields = ['quantity_returned','reason']

    def clean(self):
        cleaned_data = super().clean()
        quantity_returned = cleaned_data.get('quantity_returned')

        if quantity_returned is not None:
            if quantity_returned < 0:
                self.add_error('quantity_returned', 'Return quantity cannot be negative')
            if not cleaned_data.get('reason'):
                self.add_error('reason', 'Please provide a reason for the return')

        return cleaned_data

class DamagedInventoryForm(forms.ModelForm):
    class Meta:
        model = Damaged
        fields = ['quantity_damaged', 'damage_description']

    def clean(self):
        cleaned_data = super().clean()
        quantity_damaged = cleaned_data.get('quantity_damaged')

        if quantity_damaged is not None:
            if quantity_damaged < 0:
                self.add_error('quantity_damaged', 'Damaged quantity cannot be negative')
            if not cleaned_data.get('damage_description'):
                self.add_error('damage_description', 'Please describe the damage')

        return cleaned_data

class LoginForm(AuthenticationForm):
    username = forms.CharField(widget=forms.TextInput(
        attrs={'class': 'form-control', 'placeholder': 'Username'}))
    password = forms.CharField(widget=forms.PasswordInput(
        attrs={'class': 'form-control', 'placeholder': 'Password'}))
