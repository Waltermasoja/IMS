from django.shortcuts import redirect, render,get_object_or_404
import plotly.utils
from .models import Inventory,Return,Damaged
from django.contrib.auth.decorators import login_required
from .forms import AddInventoryForm,UpdateInventoryForm,PeriodSummaryForm,DateRangeForm,ReturnInventoryForm,DamagedInventoryForm
from django.contrib import messages
from django.db.models import Sum, F, DecimalField
from django.db.models.functions import Coalesce, TruncDate
from .models import Inventory, Sales, Return, Damaged
from .forms import AddInventoryForm, UpdateInventoryForm, DateRangeForm, ReturnInventoryForm, DamagedInventoryForm, SalesForm
import pandas as pd
import plotly.express as px
import json
import numpy
import pandas as pd
import plotly.io
from django_pandas.io import read_frame
from datetime import datetime,timedelta
from django.db.models import Sum,Count
from decimal import Decimal


@login_required
def inventory_list(request):
    inventories = Inventory.objects.all()
    context = {'title': 'Inventory list', 'inventories': inventories}
    return render(request, 'inventory/inventory_list.html', context=context)

@login_required
def per_product_view(request, pk):
    product = get_object_or_404(Inventory, pk=pk)
    context = {'inventory': product}
    return render(request, 'inventory/per_product.html', context)

@login_required 
def add_product(request):
    if request.method == 'POST':
        add_form = AddInventoryForm(data=request.POST)
        if add_form.is_valid():
            add_form.save()
            messages.success(request, "Product successfully added")
            return redirect('/inventory/')
    else:
        add_form = AddInventoryForm()    
    return render(request, 'inventory/inventory_add.html', {'form': add_form})

@login_required
def delete_inventory(request, pk):
    inventory_to_delete = get_object_or_404(Inventory, pk=pk)
    inventory_to_delete.delete()
    messages.warning(request, "Product deleted")
    return redirect('/inventory/')

@login_required
def update_inventory(request, pk):
    inventory_to_update = get_object_or_404(Inventory, pk=pk)
    
    if request.method == 'POST':
        updateform = UpdateInventoryForm(request.POST, instance=inventory_to_update)
        
        if updateform.is_valid():
            updateform.save()
            messages.success(request, "Product successfully updated")
            return redirect('/inventory/')
    else:
        updateform = UpdateInventoryForm(instance=inventory_to_update)
    
    return render(request, 'inventory/inventory_update.html', {'form': updateform})

@login_required
def create_sale(request):
    if request.method == 'POST':
        form = SalesForm(request.POST)
        if form.is_valid():
            inventory_item = form.cleaned_data['inventory_item']
            quantity_sold = form.cleaned_data['quantity_sold']
            discount_percentage = form.cleaned_data['discount_percentage']
            sale_description = form.cleaned_data['sale_description']

            # Check if there's enough stock
            if inventory_item.quantity_in_Stock >= quantity_sold:
                # Create the sale
                sale = Sales.objects.create(
                    inventory_item=inventory_item,
                    quantity_sold=quantity_sold,
                    discount_percentage=discount_percentage,
                    sale_description=sale_description
                )
                sale.save()

                # Update the inventory
                inventory_item.quantity_in_Stock -= quantity_sold
                inventory_item.quantity_sold += quantity_sold
                inventory_item.save()

                messages.success(request, f'Sale of {quantity_sold} {inventory_item.name}(s) recorded successfully.')
                return redirect('inventory:inventory_list')
            else:
                messages.error(request, f'Not enough stock. Available: {inventory_item.quantity_in_Stock}')
    else:
        form = SalesForm()

    return render(request, 'inventory/create_sale.html', {'form': form})

@login_required
def dashboard(request):
    sales_data = Sales.objects.annotate(
        total_sale=F('quantity_sold') * F('price_at_sale') * (1 - F('discount_percentage') / 100)
    ).values('sale_date__date', 'total_sale')
    
    df = pd.DataFrame(list(sales_data))
    df['sale_date__date'] = pd.to_datetime(df['sale_date__date'])
    
    sales_graph_data = df.groupby('sale_date__date')['total_sale'].sum().reset_index()
    sales_graph = px.bar(sales_graph_data, x='sale_date__date', y='total_sale', title='Sales Trend')
    sales_graph = json.dumps(sales_graph, cls=plotly.utils.PlotlyJSONEncoder)

    best_performing_product_data = Sales.objects.values('inventory_item__name').annotate(
        total_quantity_sold=Sum('quantity_sold')
    ).order_by('-total_quantity_sold')
    best_performing_product = px.bar(
        best_performing_product_data,
        x='inventory_item__name',
        y='total_quantity_sold',
        title='Best Performing Product'
    )
    best_performing_product = json.dumps(best_performing_product, cls=plotly.utils.PlotlyJSONEncoder)

    most_stocked_data = Inventory.objects.values('name', 'quantity_in_stock').order_by('-quantity_in_stock')
    most_stocked = px.pie(
        most_stocked_data,
        names='name',
        values='quantity_in_stock',
        title='Most stocked'
    )
    most_stocked = json.dumps(most_stocked, cls=plotly.utils.PlotlyJSONEncoder)

    context = {
        'sales_graph': sales_graph,
        'best_performing_product': best_performing_product,
        'most_stocked': most_stocked
    }

    return render(request, 'inventory/dashboard.html', context=context)

@login_required
def sales_summary(request):
    sales = Sales.objects.all()
    print(f"Number of sales records: {sales.count()}")

    context = {
        'sales': sales,
    }

    return render(request, 'inventory/sales_summary.html', context)


@login_required
def returnInventory(request,pk):
    inventory_item = get_object_or_404(Inventory,pk=pk)
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
    obsolete_inventory = get_object_or_404(Inventory, pk=pk)
    
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
