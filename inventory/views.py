from django.shortcuts import redirect, render,get_object_or_404
import plotly.utils
from .models import inventory, Return, Damaged, StockMovement, Sales
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
from django.db.models import Sum,Count,Max
from django.contrib.auth import login, authenticate, logout
import plotly.graph_objects as go
from django.db.models import Q
from django.utils import timezone



@login_required
def inventory_list(request):
    inventories = inventory.objects.all()
    
    # Annotate each inventory item with its sales data
    inventories = inventories.annotate(
        sales_amount=Sum('sales_records__total_amount'),
        latest_sale=Max('sales_records__sale_date')
    )
    
    context = {
        'inventories': inventories
    }
    return render(request, 'inventory/inventory_list.html', context)

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
        add_form = AddInventoryForm(request.POST)
        if add_form.is_valid():
            new_inventory = add_form.save(commit=False)
            new_inventory.save()
            
            # Create stock movement record with correct field names
            StockMovement.objects.create(
                inventory_item=new_inventory,
                movement_type='IN',
                quantity=new_inventory.quantity_in_Stock,
                reason='Initial Stock'
            )
            
            messages.success(request, 'Product added successfully!')
            return redirect('inventory')
    else:
        add_form = AddInventoryForm()
    
    return render(request, 'inventory/inventory_add.html', {
        'form': add_form,
        'title': 'Add Product'
    })
@login_required
def delete_inventory(request,pk):
    inventory_to_delete = get_object_or_404(inventory,pk=pk)
    inventory_to_delete.delete()
    messages.warning(request,"Product deleted")
    return redirect('/inventory/')


from decimal import Decimal

@login_required
def update_inventory(request, pk):
    inventory_item = get_object_or_404(inventory, pk=pk)
    
    if request.method == 'POST':
        form = UpdateInventoryForm(request.POST)
        
        if form.is_valid():
            quantity_sold = form.cleaned_data['quantity_sold']
            sale_price = form.cleaned_data['sale_price']
            discount = form.cleaned_data['discount_applied']

            # Check if enough stock is available
            if inventory_item.quantity_in_Stock - quantity_sold < 0:
                messages.error(request, "Not enough stock available.")
                return render(request, 'inventory/inventory_update.html', {'form': form})

            # Create new sale record
            sale = Sales.objects.create(
                inventory_item=inventory_item,
                quantity_sold=quantity_sold,
                sale_price=sale_price,
                discount_applied=discount,
                sale_date=timezone.now()
            )

            # Update inventory stock
            inventory_item.quantity_in_Stock -= quantity_sold
            inventory_item.save()

            messages.success(request, "Sale successfully recorded")
            return redirect('inventory')
    else:
        initial_data = {
            'sale_price': inventory_item.cost,  # Set initial sale price to cost
            'quantity_sold': 1,  # Default quantity
            'discount_applied': 0  # Default discount
        }
        form = UpdateInventoryForm(initial=initial_data)
    
    return render(request, 'inventory/inventory_update.html', {
        'form': form,
        'inventory': inventory_item
    })





@login_required
def dashboard(request):
    # Get all inventory items
    inventories = inventory.objects.all()
    
    # Get sales data
    sales_data = Sales.objects.all()
    
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
    
    # Best performing products (by sales)
    if sales_data.exists():
        sales_df = pd.DataFrame(list(Sales.objects.values('inventory_item__name')
                              .annotate(total_sales=Sum('total_amount'))
                              .order_by('-total_sales')[:5]))
        
        if not sales_df.empty:
            best_performing_product = px.bar(
                sales_df,
                x='inventory_item__name',
                y='total_sales',
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
    if inventories.exists():
        stock_df = pd.DataFrame(list(inventories.values('name', 'quantity_in_Stock')
                              .order_by('-quantity_in_Stock')[:5]))
        
        if not stock_df.empty:
            most_stocked = px.bar(
                stock_df,
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
        
        # Get sales data within date range
        sales_data = Sales.objects.filter(
            sale_date__date__range=(start_date, end_date)
        ).values('inventory_item__name').annotate(
            total_quantity=Sum('quantity_sold'),
            total_sales=Sum('total_amount'),
            total_discount=Sum('discount_applied')
        ).order_by('-total_sales')
    else:
        # Get all sales data if no date range specified
        sales_data = Sales.objects.values('inventory_item__name').annotate(
            total_quantity=Sum('quantity_sold'),
            total_sales=Sum('total_amount'),
            total_discount=Sum('discount_applied')
        ).order_by('-total_sales')
    
    # Calculate totals
    totals = {
        'total_quantity': sum(item['total_quantity'] for item in sales_data),
        'total_sales': sum(item['total_sales'] for item in sales_data),
        'total_discount': sum(item['total_discount'] for item in sales_data)
    }
    
    context = {
        'form': form,
        'sales_data': sales_data,
        'totals': totals
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


