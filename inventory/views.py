from django.shortcuts import redirect, render,get_object_or_404
import plotly.utils
from .models import inventory
from django.contrib.auth.decorators import login_required
from .forms import AddInventoryForm,UpdateInventoryForm
from django.contrib import messages
from django_pandas.io import read_frame
import plotly
import plotly.express as px
import json
import numpy
import plotly.io


@login_required
def inventory_list(request):
    inventories = inventory.objects.all()
    context= {'title':'Inventory list',
              'inventories':inventories}
    return render(request,'inventory/inventory_list.html',context=context)

@login_required
def per_product_view(request,pk):
    product = get_object_or_404(inventory,pk=pk)
    context = {
        'inventory':product
    }

    return render(request,'inventory/per_product.html',context)
@login_required
def add_product(request):
    if request.method == 'POST':
        add_form = AddInventoryForm(data=request.POST)
        if add_form.is_valid():
            new_inventory = add_form.save(commit=False)
            new_inventory.sales = float(add_form.data['cost']) * float(add_form.data['quantity_sold'])
            new_inventory.save()
            messages.success(request,"You have successfully added inventory")
            return redirect('/inventory/')
        
    else :
        add_form = AddInventoryForm()    
    
    return render(request,'inventory/inventory_add.html',{'form':add_form})
@login_required
def delete_inventory(request,pk):
    inventory_to_delete = get_object_or_404(inventory,pk=pk)
    inventory_to_delete.delete()
    messages.danger(request,"You have successfully deleted product")
    return redirect('/inventory/')

@login_required
def update_inventory(request,pk):
    inventory_to_update = get_object_or_404(inventory,pk=pk)
    if request.method == 'POST':
        updateform = UpdateInventoryForm(request.POST,instance=inventory_to_update)
        if updateform.is_valid():
            inventory.name = updateform.data['name']
            inventory.cost = updateform.data['cost']
            inventory.quantity_in_Stock = updateform.data['quantity_in_Stock']
            inventory.quantity_sold = updateform.data['quantity_sold']
            inventory_to_update.sales = float(updateform.data['cost']) *float(updateform.data['quantity_sold'])
            inventory_to_update.save()
            messages.success(request,"You have successfully updated product")
            return redirect('/inventory/')
    else:
        updateform = UpdateInventoryForm(instance=inventory_to_update)    
            


    return render(request,'inventory/inventory_update.html',{'form':updateform})

@login_required
def dashboard(request):
    inventories = inventory.objects.all()
    df = read_frame(inventories)

    sales_graph_data = df.groupby(by='last_sale_date',as_index=False,sort=False)['sales'].sum()
    sales_graph = px.line(sales_graph_data,x='last_sale_date',y='sales',title='Sales Trend')
    sales_graph = json.dumps(sales_graph,cls=plotly.utils.PlotlyJSONEncoder)

    best_performing_product_df = df.groupby(by='name').sum().sort_values(by='quantity_sold')
    best_performing_product = px.bar(best_performing_product_df,
                                     x= best_performing_product_df.index,
                                     y = best_performing_product_df.quantity_sold,
                                     title='Best Performing Product')
    
    best_performing_product = json.dumps(best_performing_product,cls=plotly.utils.PlotlyJSONEncoder)

    most_stocked_df = df.groupby(by='name').sum().sort_values(by='quantity_in_Stock')
    most_stocked = px.pie(most_stocked_df,
                                     names= most_stocked_df.index,
                                     values = most_stocked_df.quantity_in_Stock,
                                     title='Most stocked')
    
    most_stocked = json.dumps(most_stocked,cls=plotly.utils.PlotlyJSONEncoder)

    context = {
        'sales_graph' : sales_graph,
        'best_performing_product': best_performing_product,
        'most_stocked': most_stocked
    }

    return render(request,'inventory/dashboard.html',context=context)
           