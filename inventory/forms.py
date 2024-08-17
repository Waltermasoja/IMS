from django.forms import ModelForm
from .models import inventory,Return,Damaged
from django import forms

class AddInventoryForm(ModelForm):
    class Meta:
        model = inventory
        fields = ['name','cost','quantity_in_Stock','quantity_sold','description']

class UpdateInventoryForm(ModelForm):
    class Meta :
        model = inventory
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
