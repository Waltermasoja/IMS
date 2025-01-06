from django import forms
from django.forms import ModelForm
from .models import inventory, Return, Damaged, Sales

class AddInventoryForm(ModelForm):
    class Meta:
        model = inventory
        fields = ['name', 'cost', 'quantity_in_Stock', 'description', 'label', 'size']

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
    start_date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))
    end_date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))
