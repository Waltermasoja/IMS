from django.forms import ModelForm
from .models import inventory

class AddInventoryForm(ModelForm):
    class Meta:
        model = inventory
        fields = ['name','cost','quantity_in_Stock','quantity_sold','description']

class UpdateInventoryForm(ModelForm):
    class Meta :
        model = inventory
        fields = ['name', 'cost', 'quantity_in_Stock', 'quantity_sold']
