from django.forms import ModelForm
from .models import Inventory,Return,Damaged, Sales
from django import forms

class AddInventoryForm(ModelForm):
    class Meta:
        model = Inventory
        fields = ['name','cost','quantity_in_Stock','quantity_sold','description']

class UpdateInventoryForm(ModelForm):
    class Meta :
        model = Inventory
        fields = ['name', 'cost',  'quantity_sold','sell']

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

    def cleanQuantityReturned(self):
        quaantity_returned = self.cleaned_data.get('quantity_returned')
        if quaantity_returned < 0 :
            raise forms.ValidationError("Quantity returned cannot be negative")
        return quaantity_returned 

# class DamagedInventoryForm(forms.ModelForm):
#     class Meta:
#         model = Damaged
#         fields = ['quantity_damaged','damage_description']

#     def cleanQuantityReturned(self):
#         quantity_damaged = self.cleaned_data.get('quantity_damaged')
#         if quantity_damaged < 0 :
#             raise forms.ValidationError("Quantity returned cannot be negative")
#         return quantity_damaged   

class DamagedInventoryForm(forms.ModelForm):
    class Meta:
        model = Damaged
        fields = ['quantity_damaged', 'damage_description']

    def clean_quantity_damaged(self):
        quantity_damaged = self.cleaned_data.get('quantity_damaged')
        if quantity_damaged < 0:
            raise forms.ValidationError("Quantity damaged cannot be negative")
        return quantity_damaged

class SalesForm(forms.ModelForm):
    class Meta:
        model = Sales
        fields = ['quantity_sold','sale_description','discount_percentage']

    def clean_quantity_sold(self):
        quantity_sold = self.cleaned_data.get('quantity_sold')
        if quantity_sold < 0:
            raise forms.ValidationError("Quantity sold cannot be negative")
        return quantity_sold
    
    def clean_discount(self):
        discount = self.cleaned_data.get('discount')
        if discount < 0 or discount > 100:
            raise forms.ValidationError("Discount must be between 0 and 100")
        return discount

class SalesForm(forms.ModelForm):
    class Meta:
        model = Sales
        fields = ['inventory_item', 'quantity_sold', 'discount_percentage', 'sale_description']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['inventory_item'].queryset = Inventory.objects.filter(quantity_in_Stock__gt=0)
        self.fields['discount_percentage'].widget.attrs.update({'step': '0.01', 'min': '0', 'max': '100'})
