from django.shortcuts import redirect, render,get_object_or_404
import plotly.utils
from .models import inventory,Return,Damaged,StockMovement
from django.contrib.auth.decorators import login_required
from .forms import AddInventoryForm,UpdateInventoryForm,PeriodSummaryForm,DateRangeForm,ReturnInventoryForm,DamagedInventoryForm
from django.contrib import messages
import plotly
import plotly.express as px
import json
import numpy
import pandas as pd
import plotly.io
from django_pandas.io import read_frame
from datetime import datetime,timedelta
from django.db.models import Sum,Count



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
            messages.success(request,"Product successfully added")
            return redirect('/inventory/')
        
    else :
        add_form = AddInventoryForm()    
    
    return render(request,'inventory/inventory_add.html',{'form':add_form})
@login_required
def delete_inventory(request,pk):
    inventory_to_delete = get_object_or_404(inventory,pk=pk)
    inventory_to_delete.delete()
    messages.warning(request,"Product deleted")
    return redirect('/inventory/')


from decimal import Decimal

@login_required
def update_inventory(request, pk):
    inventory_to_update = get_object_or_404(inventory, pk=pk)
    
    if request.method == 'POST':
        updateform = UpdateInventoryForm(request.POST, instance=inventory_to_update)
        
        if updateform.is_valid():
            updated_quantity_sold = int(updateform.cleaned_data['quantity_sold'])
            sell = updateform.cleaned_data.get('sell', Decimal('0.00'))
            cost = updateform.cleaned_data.get('cost', Decimal('0.00'))

            # Ensure correct values
            sell = Decimal(sell) if sell is not None else Decimal('0.00')
            cost = Decimal(cost) if cost is not None else Decimal('0.00')

            # Calculate discount and updated cost
            discount = (sell / Decimal('100.00')) * cost
            updated_cost = cost - discount

            if inventory_to_update.quantity_in_Stock - updated_quantity_sold < 0:
                messages.error(request, "Not enough stock available.")
                return render(request, 'inventory/inventory_update.html', {'form': updateform})

            # Update fields
            inventory_to_update.name = updateform.cleaned_data['name']
            inventory_to_update.cost = updated_cost
            inventory_to_update.quantity_sold = updated_quantity_sold
            inventory_to_update.quantity_in_Stock -= updated_quantity_sold
            inventory_to_update.sales = updated_cost * updated_quantity_sold
            inventory_to_update.size = inventory_to_update.size

            # Update cumulative fields
            inventory_to_update.cummulative_quantity_sold += updated_quantity_sold
            inventory_to_update.cumulative_sales += inventory_to_update.sales

            inventory_to_update.save()
            messages.success(request, "Product successfully updated")
            return redirect('/inventory/')
    else:
        updateform = UpdateInventoryForm(instance=inventory_to_update)
    
    return render(request, 'inventory/inventory_update.html', {'form': updateform})





@login_required
def dashboard(request):
    inventories = inventory.objects.all()
    df = read_frame(inventories)
    df['last_sale_date'] = pd.to_datetime(df['last_sale_date']).dt.date

    sales_graph_data = df.groupby(by='last_sale_date',as_index=False,sort=False)['sales'].sum()
    sales_graph_data['last_sale_date'] = pd.to_datetime(sales_graph_data['last_sale_date'])
    sales_graph = px.bar(sales_graph_data,x='last_sale_date',y='sales',title='Sales Trend')
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

@login_required
def sales_summary(request):
    form = DateRangeForm(request.GET or None)
    
    if form.is_valid():
        start_date = form.cleaned_data['start_date']
        end_date = form.cleaned_data['end_date']
        
        # Aggregate total sales and quantities per product with cumulative totals
        sales_data = inventory.objects.filter(
            last_sale_date__range=(start_date, end_date)
        ).values('name').annotate(
            total_quantity_sold=Sum('quantity_sold'),
            total_sales=Sum('sales'),
            cumulative_quantity_sold=Sum('cummulative_quantity_sold'),
            cumulative_sales=Sum('cumulative_sales')
        ).order_by('name')

        # Convert to DataFrame for display
        df = pd.DataFrame(list(sales_data))
        cumulative_sales_data = df.to_dict(orient='records')
    
    else:
        sales_data = inventory.objects.values('name').annotate(
            total_quantity_sold=Sum('quantity_sold'),
            total_sales=Sum('sales'),
            cumulative_quantity_sold=Sum('cummulative_quantity_sold'),
            cumulative_sales=Sum('cumulative_sales')
        ).order_by('name')

        cumulative_sales_data = sales_data
    
    context = {
        'form': form,
        'sales_data': cumulative_sales_data
    }
    
    return render(request, 'inventory/sales_summary.html', context)


@login_required
def returnInventory(request,pk):
    inventory_item = get_object_or_404(inventory,pk=pk)
    if request.method == 'POST':
        form = ReturnInventoryForm(request.POST)
        if form.is_valid():
            quantity_returned = form.cleaned_data['quantity_returned']
            return_instance = Return(quantity_returned=quantity_returned, inventory_item=inventory_item)
            inventory_item.quantity_in_Stock += quantity_returned
            inventory_item.save()
            return_instance.save()
            messages.success(request, f"Successfully returned {quantity_returned} item(s) of {inventory_item.name}")
            return redirect('/inventory/')

           
    else:
        form = ReturnInventoryForm()

    return render(request,'inventory/return_inventory.html',{'form':form,'inventory':inventory_item})    


@login_required
def return_summary(request):
    returns = Return.objects.all().order_by('-return_date') 
    total_returns = returns.aggregate(total_quantity_returned=Sum('quantity_returned'))

    context = {
        'returns':returns,
        'total_returns':total_returns
    }
    return render(request,'inventory/return_summary.html',context)


@login_required
def obsolate_summary(request):
    damages = Damaged.objects.all().order_by('-return_date') 
    total_damages = damages.aggregate(total_quantity_damaged=Sum('quantity_damaged'))

    context = {
        'damages':damages,
        'total_damages':total_damages
    }
    return render(request,'inventory/damages_summary.html',context)


@login_required
def damagedInventory(request, pk):
    obsolete_inventory = get_object_or_404(inventory, pk=pk)
    
    if request.method == 'POST':
        form = DamagedInventoryForm(request.POST)
        
        if form.is_valid():
            quantity_damaged = form.cleaned_data['quantity_damaged']
            damage_description = form.cleaned_data['damage_description']

            # Create a Damaged instance
            damaged_instance = Damaged(
                inventory_item=obsolete_inventory,
                quantity_damaged=quantity_damaged,
                damage_description=damage_description
            )
            damaged_instance.save()

            # Update the inventory
            obsolete_inventory.quantity_in_Stock -= quantity_damaged
            obsolete_inventory.save()

            messages.success(request, f"{quantity_damaged} item(s) of {obsolete_inventory.name} successfully marked as damaged.")
            return redirect('/inventory/')
        else:
            messages.error(request, "Form submission failed. Please check your input.")
    else:
        form = DamagedInventoryForm()
    
    return render(request, 'inventory/damaged_inventory.html', {'form': form, 'inventory': obsolete_inventory})

@login_required
def stock_movement_summary(request, pk):
    inventory_items = get_object_or_404(inventory, pk=pk)
    stock_movements = StockMovement.objects.filter(inventory_item=inventory_items).order_by('-stock_date')

    context = {
        'inventory_items': inventory_items,
        'stock_movements': stock_movements,
    }

    return render(request, 'inventory/stock_movement_summary.html', context)

