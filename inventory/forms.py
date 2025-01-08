from django import forms
from django.forms import ModelForm
from .models import Inventory, Return, Damaged, Sales

class AddInventoryForm(ModelForm):
    class Meta:
        model = Inventory
        fields = [
            'bought_from',
            'name',
            'purchase_price',
            'selling_price',
            'quantity_in_Stock',
            'description',
            'label',
            'size',
            'on_sale'
        ]

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

        if selling_price and purchase_price and selling_price < purchase_price:
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
