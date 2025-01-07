from django.shortcuts import redirect, render,get_object_or_404
import plotly.utils
from .models import Inventory, Return, Damaged, StockMovement, Sales, missing_inventory
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
from django.core.cache import cache
from django.views.decorators.http import condition



@login_required
def inventory_list(request):
    inventories = Inventory.objects.all()
    
    # Renamed annotations to avoid conflicts with model properties
    inventories = inventories.annotate(
        total_sales_amount=Sum('sales_records__total_amount'),  # Changed from sales_amount
        latest_sale_date=Max('sales_records__sale_date')       # Changed from latest_sale
    )
    
    context = {
        'inventories': inventories
    }
    return render(request, 'inventory/inventory_list.html', context)

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
        form = AddInventoryForm(request.POST)
        if form.is_valid():
            new_inventory = form.save(commit=False)
            new_inventory.save()
            
            # Create stock movement record
            StockMovement.objects.create(
                inventory_item=new_inventory,
                movement_type='IN',
                quantity=new_inventory.quantity_in_Stock,
                reason='Initial Stock'
            )
            
            messages.success(request, f'Product "{new_inventory.name}" added successfully!')
            return redirect('inventory')
    else:
        form = AddInventoryForm()
    
    return render(request, 'inventory/inventory_add.html', {
        'form': form,
        'title': 'Add New Product'
    })
@login_required
def delete_inventory(request,pk):
    inventory_to_delete = get_object_or_404(Inventory,pk=pk)
    inventory_to_delete.delete()
    messages.warning(request,"Product deleted")
    return redirect('/inventory/')


from decimal import Decimal

@login_required
def update_inventory(request, pk):
    inventory_item = get_object_or_404(Inventory, pk=pk)
    
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
            'sale_price': inventory_item.selling_price,  # Set initial sale price to cost
            'quantity_sold': 1,  # Default quantity
            'discount_applied': 0  # Default discount
        }
        form = UpdateInventoryForm(initial=initial_data)
    
    return render(request, 'inventory/inventory_update.html', {
        'form': form,
        'inventory': inventory_item
    })





def get_dashboard_etag(request):
    return f"dashboard-{cache.get('dashboard_version', '1.0')}"

class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return str(obj)
        return super(DecimalEncoder, self).default(obj)

@login_required
@condition(etag_func=get_dashboard_etag)
def dashboard(request):
    try:
        # Dashboard statistics
        total_products = Inventory.objects.count()
        low_stock = Inventory.objects.filter(quantity_in_Stock__lte=10).count()
        out_of_stock = Inventory.objects.filter(quantity_in_Stock=0).count()
        total_sales = Sales.objects.aggregate(total=Sum('total_amount'))['total'] or 0

        # Best Performing Products Chart
        best_performing = list(Sales.objects.values('inventory_item__name')
                             .annotate(total_sales=Sum('total_amount'))
                             .order_by('-total_sales')[:5])
        
        best_performing_data = {
            'data': [{
                'type': 'bar',
                'x': [item['inventory_item__name'] for item in best_performing] if best_performing else ['No Data'],
                'y': [float(item['total_sales']) for item in best_performing] if best_performing else [0],
                'marker': {'color': '#0d6efd'}
            }],
            'layout': {
                'title': 'Top 5 Products by Sales',
                'xaxis': {'title': 'Products'},
                'yaxis': {'title': 'Total Sales ($)'},
                'annotations': [] if best_performing else [{
                    'text': 'No Data to Display',
                    'xref': 'paper',
                    'yref': 'paper',
                    'showarrow': False,
                    'font': {
                        'size': 20,
                        'color': 'grey'
                    },
                    'x': 0.5,
                    'y': 0.5
                }]
            }
        }

        # Most Stocked Products Chart
        most_stocked = list(Inventory.objects.values('name', 'quantity_in_Stock')
                           .order_by('-quantity_in_Stock')[:5])
        
        most_stocked_data = {
            'data': [{
                'type': 'bar',
                'x': [item['name'] for item in most_stocked] if most_stocked else ['No Data'],
                'y': [item['quantity_in_Stock'] for item in most_stocked] if most_stocked else [0],
                'marker': {'color': '#1cc88a'}
            }],
            'layout': {
                'title': 'Top 5 Most Stocked Products',
                'xaxis': {'title': 'Products'},
                'yaxis': {'title': 'Quantity in Stock'},
                'annotations': [] if most_stocked else [{
                    'text': 'No Data to Display',
                    'xref': 'paper',
                    'yref': 'paper',
                    'showarrow': False,
                    'font': {
                        'size': 20,
                        'color': 'grey'
                    },
                    'x': 0.5,
                    'y': 0.5
                }]
            }
        }

        context = {
            'total_products': total_products,
            'low_stock': low_stock,
            'out_of_stock': out_of_stock,
            'total_sales': total_sales,
            'best_performing_product': json.dumps(best_performing_data, cls=DecimalEncoder),
            'most_stocked': json.dumps(most_stocked_data)
        }

        return render(request, 'inventory/dashboard.html', context)

    except Exception as e:
        print(f"Error in dashboard view: {str(e)}")
        empty_chart_data = {
            'data': [{
                'type': 'bar',
                'x': ['No Data'],
                'y': [0]
            }],
            'layout': {
                'annotations': [{
                    'text': 'No Data to Display',
                    'xref': 'paper',
                    'yref': 'paper',
                    'showarrow': False,
                    'font': {
                        'size': 20,
                        'color': 'grey'
                    },
                    'x': 0.5,
                    'y': 0.5
                }]
            }
        }
        
        context = {
            'total_products': 0,
            'low_stock': 0,
            'out_of_stock': 0,
            'total_sales': 0,
            'best_performing_product': json.dumps(empty_chart_data),
            'most_stocked': json.dumps(empty_chart_data)
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
    results = Inventory.objects.filter(name__icontains=query)
    return render(request, 'inventory/search_results.html', {'results': results})

@login_required
def logout_view(request):
    logout(request)
    return redirect('login')

@login_required
def search_results(request):
    query = request.GET.get('q', '')
    if query:
        results = Inventory.objects.filter(
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


