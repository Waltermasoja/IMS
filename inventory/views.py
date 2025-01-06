from django.shortcuts import redirect, render,get_object_or_404
import plotly.utils
from .models import inventory, Return, Damaged, StockMovement
from django.contrib.auth.decorators import login_required
from .forms import AddInventoryForm,UpdateInventoryForm,PeriodSummaryForm,DateRangeForm,ReturnInventoryForm,DamagedInventoryForm,LoginForm
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
from django.contrib.auth import login, authenticate, logout
import plotly.graph_objects as go
from django.db.models import Q



@login_required
def inventory_list(request):
    inventories = inventory.objects.all()
    context= {'title':'Inventory list',
              'inventories':inventories}
    return render(request,'inventory/inventory_list.html',context=context)

@login_required
def per_product_view(request,pk):
    product = get_object_or_404(Inventory,pk=pk)
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
    inventory_to_delete = get_object_or_404(Inventory,pk=pk)
    inventory_to_delete.delete()
    messages.warning(request,"Product deleted")
    return redirect('/inventory/')


from decimal import Decimal

@login_required
def update_inventory(request, pk):
    inventory_to_update = get_object_or_404(Inventory, pk=pk)
    
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
    # Get all inventory items
    inventories = Inventory.objects.all()
    
    # Create empty figures for when there's no data
    empty_fig = go.Figure()
    empty_fig.update_layout(
        title="No Data Available",
        xaxis_title="No Data",
        yaxis_title="No Data",
        height=400,
        margin=dict(t=30, l=10, r=10, b=30),
        annotations=[{
            'text': "No data available to display",
            'xref': "paper",
            'yref': "paper",
            'showarrow': False,
            'font': {'size': 20}
        }]
    )
    
    # Convert to DataFrame and fix data types
    df = pd.DataFrame(list(inventories.values()))
    
    # Best performing products (by sales)
    if not df.empty and 'name' in df.columns and 'sales' in df.columns:
        # Convert sales to numeric, replacing any invalid values with 0
        df['sales'] = pd.to_numeric(df['sales'], errors='coerce').fillna(0)
        
        best_performing_product_df = df.nlargest(5, 'sales')[['name', 'sales']]
        if not best_performing_product_df.empty:
            best_performing_product = px.bar(
                best_performing_product_df,
                x='name',
                y='sales',
                title='Best Performing Products',
                height=400,
                template='plotly_white'
            )
            best_performing_product.update_layout(
                margin=dict(t=30, l=10, r=10, b=30)
            )
        else:
            best_performing_product = empty_fig
    else:
        best_performing_product = empty_fig

    # Most stocked products
    if not df.empty and 'name' in df.columns and 'quantity_in_Stock' in df.columns:
        # Convert quantity_in_Stock to numeric
        df['quantity_in_Stock'] = pd.to_numeric(df['quantity_in_Stock'], errors='coerce').fillna(0)
        
        most_stocked_df = df.nlargest(5, 'quantity_in_Stock')[['name', 'quantity_in_Stock']]
        if not most_stocked_df.empty:
            most_stocked = px.bar(
                most_stocked_df,
                x='name',
                y='quantity_in_Stock',
                title='Most Stocked Products',
                height=400,
                template='plotly_white'
            )
            most_stocked.update_layout(
                margin=dict(t=30, l=10, r=10, b=30)
            )
        else:
            most_stocked = empty_fig
    else:
        most_stocked = empty_fig

    context = {
        'best_performing_product': best_performing_product.to_html(),
        'most_stocked': most_stocked.to_html(),
        'total_products': inventories.count(),
        'low_stock': inventories.filter(quantity_in_Stock__lte=10).count(),
        'out_of_stock': inventories.filter(quantity_in_Stock=0).count(),
    }
    
    return render(request, 'inventory/dashboard.html', context)

@login_required
def sales_summary(request):
    form = DateRangeForm(request.GET or None)
    
    if form.is_valid():
        start_date = form.cleaned_data['start_date']
        end_date = form.cleaned_data['end_date']
        
        # Aggregate total sales and quantities per product with cumulative totals
        sales_data = Inventory.objects.filter(
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
        sales_data = Inventory.objects.values('name').annotate(
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

@login_required
def stock_movement_summary(request, pk):
    inventory_items = get_object_or_404(Inventory, pk=pk)
    stock_movements = StockMovement.objects.filter(inventory_item=inventory_items).order_by('-stock_date')

    context = {
        'inventory_items': inventory_items,
        'stock_movements': stock_movements,
    }

    return render(request, 'inventory/stock_movement_summary.html', context)

def login_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            messages.success(request, f'Welcome back, {username}!')
            return redirect('dashboard')  # Changed from 'inventory' to 'dashboard'
        else:
            messages.error(request, 'Invalid username or password.')
    return render(request, 'inventory_system/login.html')

def search(request):
    query = request.GET.get('q')
    results = inventory.objects.filter(name__icontains=query)
    return render(request, 'inventory/search_results.html', {'results': results})

@login_required
def logout_view(request):
    logout(request)
    return redirect('login')

@login_required
def search_results(request):
    query = request.GET.get('q', '')
    if query:
        results = inventory.objects.filter(
            Q(name__icontains=query) |
            Q(description__icontains=query) |
            Q(label__icontains=query) |
            Q(size__icontains=query)
        )
    else:
        results = []
    
    context = {
        'query': query,
        'results': results,
        'count': len(results)
    }
    return render(request, 'inventory/search_results.html', context)


