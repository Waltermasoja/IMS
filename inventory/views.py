from django.shortcuts import redirect, render,get_object_or_404
import plotly.utils
from .models import Inventory, Return, Damaged, StockMovement, Sales, missing_inventory, Inventory_category
from django.contrib.auth.decorators import login_required
from .forms import AddInventoryForm,UpdateInventoryForm,DateRangeForm,ReturnInventoryForm,DamagedInventoryForm,Inventory_categoryForm
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
from django.db.models import Sum, Count, F, ExpressionWrapper, DecimalField, Q
from django.db.models.functions import TruncMonth, Coalesce, ExtractMonth
from django.utils import timezone
from datetime import timedelta
from .models import Inventory, Sales, Return, Damaged, Inventory_category
import json
import calendar
from django.urls import reverse
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.http import require_http_methods
import decimal



@login_required
def inventory_list(request):
    inventories = Inventory.objects.all()
    categories = Inventory_category.objects.all()
    
    # Renamed annotations to avoid conflicts with model properties
    inventories = inventories.annotate(
        total_sales_amount=Sum('sales_records__total_amount'),  # Changed from sales_amount
        latest_sale_date=Max('sales_records__sale_date')       # Changed from latest_sale
    )
    
    context = {
        'inventories': inventories,
        'categories': categories,
    }
    return render(request, 'inventory/inventory_list.html', context)

@login_required
@require_http_methods(["POST"])
def update_inventory(request, pk):
    inventory = get_object_or_404(Inventory, pk=pk)
    
    try:
        # Get form data
        data = request.POST.dict()
        data['on_sale'] = request.POST.get('on_sale') == 'on'
        
        # Convert numeric fields
        data['purchase_price'] = Decimal(data['purchase_price'])
        data['selling_price'] = Decimal(data['selling_price'])
        data['quantity_in_Stock'] = int(data['quantity_in_Stock'])
        data['size'] = int(data.get('size', 0))
        
        # Validate prices
        if data['selling_price'] < data['purchase_price']:
            raise ValueError("Selling price cannot be less than purchase price")
        
        # Update inventory
        for key, value in data.items():
            if key != 'csrfmiddlewaretoken':
                setattr(inventory, key, value)
        
        inventory.save()
        
        return JsonResponse({
            'success': True
        })
        
    except (ValueError, decimal.InvalidOperation) as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })

@login_required
def per_product_view(request, pk):
    inventory = get_object_or_404(Inventory, pk=pk)
    
    # Get sales data with return information
    sales_data = Sales.objects.filter(inventory_item=inventory)
    
    total_sales = sum(sale.total_amount for sale in sales_data)
    total_quantity_sold = sum(sale.quantity_sold for sale in sales_data)
    total_returns = sum(sale.quantity_returned for sale in sales_data)
    net_quantity = total_quantity_sold - total_returns
    
    context = {
        'inventory': inventory,
        'total_sales': total_sales,
        'total_quantity_sold': total_quantity_sold,
        'total_returns': total_returns,
        'net_quantity': net_quantity,
    }
    print(inventory.last_sale_date)

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
@require_http_methods(["GET", "POST"])
def make_sale(request, pk):
    inventory = get_object_or_404(Inventory, pk=pk)
    
    if request.method == 'POST':
        try:
            quantity = int(request.POST.get('quantity_sold'))
            sale_price = Decimal(request.POST.get('sale_price'))
            discount = Decimal(request.POST.get('discount_applied', 0))
            
            if quantity <= 0:
                raise ValueError("Quantity must be greater than 0")
            
            if quantity > inventory.quantity_in_Stock:
                raise ValueError("Not enough stock available")
            
            if sale_price <= 0:
                raise ValueError("Sale price must be greater than 0")
            
            # Create the sale
            sale = Sales.objects.create(
                inventory_item=inventory,
                quantity_sold=quantity,
                sale_price=sale_price,
                discount_applied=discount
            )
            
            # Update inventory
            inventory.quantity_in_Stock -= quantity
            inventory.save()
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'sale_id': sale.id
                })
            return redirect('inventory')
            
        except (ValueError, decimal.InvalidOperation) as e:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': False,
                    'error': str(e)
                })
            messages.error(request, str(e))
            return redirect('make_sale', pk=pk)
    
    # GET request - we don't need this anymore as we're using modal
    return redirect('inventory')





# def get_dashboard_etag(request):
#     return f"dashboard-{cache.get('dashboard_version', '1.0')}"

# class DecimalEncoder(json.JSONEncoder):
#     def default(self, obj):
#         if isinstance(obj, Decimal):
#             return str(obj)
#         return super(DecimalEncoder, self).default(obj)

@login_required
# @condition(etag_func=get_dashboard_etag)


@login_required
def sales_summary(request):
    form = DateRangeForm(request.GET or None)
    sales = Sales.objects.all().order_by('-sale_date')
    
    if form.is_valid():
        start_date = form.cleaned_data['start_date']
        end_date = form.cleaned_data['end_date']
        if start_date and end_date:
            sales = sales.filter(sale_date__date__range=[start_date, end_date])

    # Calculate totals
    total_amount = sum(sale.total_amount for sale in sales)
    total_quantity_sold = sum(sale.quantity_sold for sale in sales)
    total_returns = sum(sale.quantity_returned for sale in sales)
    net_quantity = total_quantity_sold - total_returns

    context = {
        'sales': sales,
        'form': form,
        'total_amount': total_amount,
        'total_quantity_sold': total_quantity_sold,
        'total_returns': total_returns,
        'net_quantity': net_quantity,
    }
    
    return render(request, 'inventory/sales_summary.html', context)


@login_required
def returnInventory(request, pk):
    inventory_item = get_object_or_404(Inventory, pk=pk)
    if request.method == 'POST':
        form = ReturnInventoryForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    receipt_number = form.cleaned_data['receipt_number']
                    quantity_returned = form.cleaned_data['quantity_returned']
                    reason = form.cleaned_data['reason']
                    
                    # Try to find the associated sale
                    try:
                        sale = Sales.objects.get(
                            receipt_number=receipt_number,
                            inventory_item=inventory_item
                        )
                        
                        # Check if return quantity is valid
                        if quantity_returned > sale.remaining_quantity:
                            messages.error(
                                request, 
                                f"Return quantity ({quantity_returned}) exceeds remaining quantity ({sale.remaining_quantity})"
                            )
                            return redirect('returnInventory', pk=pk)
                            
                        # Update the sale's returned quantity
                        sale.quantity_returned += quantity_returned
                        sale.save()
                            
                    except Sales.DoesNotExist:
                        messages.warning(request, "No matching sale found for this receipt number")
                        sale = None
                    
                    # Create return record
                    return_instance = Return.objects.create(
                        quantity_returned=quantity_returned,
                        inventory_item=inventory_item,
                        reason=reason,
                        receipt_number=receipt_number,
                        sale=sale
                    )
                    sale.return_record.add(return_instance)

                    # Create stock movement record
                    StockMovement.objects.create(
                        inventory_item=inventory_item,
                        movement_type='IN',
                        quantity=quantity_returned,
                        reason=f'Return: {reason} (Receipt: {receipt_number})'
                    )

                    # Update inventory stock
                    inventory_item.quantity_in_Stock += quantity_returned
                    inventory_item.save()

                    messages.success(
                        request, 
                        f"Successfully returned {quantity_returned} item(s) of {inventory_item.name}"
                    )
                    return redirect('inventory')
                    
            except Exception as e:
                messages.error(request, f"Error processing return: {str(e)}")
                return redirect('returnInventory', pk=pk)
    else:
        form = ReturnInventoryForm()

    # Get recent sales for this product
    recent_sales = Sales.objects.filter(
        inventory_item=inventory_item
    ).order_by('-sale_date')[:5]  # Show last 5 sales

    context = {
        'form': form,
        'inventory': inventory_item,
        'title': f'Return {inventory_item.name}',
        'recent_sales': recent_sales
    }
    return render(request, 'inventory/return_inventory.html', context)


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
    inventory_item = get_object_or_404(Inventory, pk=pk)
    form = DateRangeForm(request.GET or None)
    
    stock_movements = StockMovement.objects.filter(inventory_item=inventory_item).order_by('stock_date')
    
    if form.is_valid():
        start_date = form.cleaned_data['start_date']
        end_date = form.cleaned_data['end_date']
        stock_movements = stock_movements.filter(stock_date__range=(start_date, end_date))

    # Calculate running balance for each movement
    running_balance = 0
    movements_with_balance = []
    
    for movement in stock_movements:
        opening_balance = running_balance
        if movement.movement_type == 'IN':
            running_balance += movement.quantity
        else:
            running_balance -= movement.quantity
            
        movements_with_balance.append({
            'movement': movement,
            'opening_balance': opening_balance,
            'closing_balance': running_balance
        })

    context = {
        'inventory_item': inventory_item,
        'stock_movements': movements_with_balance,
        'form': form
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

# def get_dashboard_etag(request):
#     return f"dashboard-{cache.get('dashboard_version', '1.0')}"

# class DecimalEncoder(json.JSONEncoder):
#     def default(self, obj):
#         if isinstance(obj, Decimal):
#             return str(obj)
#         return super(DecimalEncoder, self).default(obj)

@login_required
# @condition(etag_func=get_dashboard_etag)
def dashboard(request):
    # Get current date and last 6 months
    end_date = timezone.now()
    start_date = end_date - timedelta(days=180)
    
    # Calculate metrics
    metrics = {
        'total_products': Inventory.objects.count(),
        'total_sales': float(Sales.objects.aggregate(total=Sum('total_amount'))['total'] or 0),
        'low_stock': Inventory.objects.filter(quantity_in_Stock__lte=10).count(),
        'out_of_stock': Inventory.objects.filter(quantity_in_Stock=0).count(),
    }
    
    # Get monthly sales data
    monthly_sales = (Sales.objects
        .filter(sale_date__range=(start_date, end_date))
        .annotate(month=TruncMonth('sale_date'))
        .values('month')
        .annotate(total=Sum('total_amount'))
        .order_by('month'))
    
    # Get top selling products
    top_products = (Sales.objects
        .values('inventory_item__name')
        .annotate(total_sales=Sum('total_amount'))
        .order_by('-total_sales')[:5])
    
    # Get recent sales
    recent_sales = Sales.objects.select_related('inventory_item').order_by('-sale_date')[:10]

    
    # Format data for charts
    sales_data = {
        'months': [sale['month'].strftime("%b %Y") for sale in monthly_sales],
        'values': [float(sale['total']) for sale in monthly_sales]
    }
    
    products_data = {
        'names': [product['inventory_item__name'] for product in top_products],
        'values': [float(product['total_sales']) for product in top_products]
    }
    
    context = {
        'metrics': metrics,
        'sales_data': json.dumps(sales_data),
        'products_data': json.dumps(products_data),
        'recent_sales': recent_sales,
    }
    
    return render(request, 'inventory/dashboard.html', context)

def calculate_growth_percentage(model, date_field):
    # Implementation for calculating growth percentage
    today = timezone.now()
    previous_month = today.replace(day=1) - timedelta(days=1)
    previous_month_start = previous_month.replace(day=1)
    previous_month_end = previous_month.replace(day=calendar.monthrange(previous_month.year, previous_month.month)[1])
    
    # Changed created_at to created_date
    inventory_count = model.objects.filter(created_date__date__range=(previous_month_start, previous_month_end)).count()
    current_month_count = model.objects.filter(created_date__date__range=(today.replace(day=1), today)).count()
    
    if inventory_count == 0:
        return 100
    growth_percentage = ((current_month_count - inventory_count) / inventory_count) * 100
    return round(growth_percentage, 2)


def calculate_sales_growth():
    # Implementation for calculating sales growth
    today = timezone.now()
    thirty_days_ago = today - timedelta(days=30)
    previous_month = today.replace(day=1) - timedelta(days=1)
    previous_month_start = previous_month.replace(day=1)
    previous_month_end = previous_month.replace(day=calendar.monthrange(previous_month.year, previous_month.month)[1])
    sales_data = Sales.objects.filter(sale_date__date__range=(previous_month_start, previous_month_end))
    total_sales = sales_data.aggregate(total=Sum('total_amount'))['total'] or 0
    current_month_sales = Sales.objects.filter(sale_date__date__range=(today.replace(day=1), today)).aggregate(total=Sum('total_amount'))['total'] or 0
    if total_sales == 0:
        return 100
    sales_growth = ((current_month_sales - total_sales) / total_sales) * 100
    return round(sales_growth, 2)

def get_monthly_sales_data():
    # Dummy data for the last 6 months
    months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun']
    dummy_sales = [1500, 2300, 1800, 2500, 2100, 2800]  # Example sales figures
    
    return {
        'labels': months,
        'series': [dummy_sales]  # Chartist expects series as an array of arrays
    }


@login_required
def inventory_category(request):
    categories = Inventory_category.objects.all()
    
    # Calculate total stock value and items count for each category
    category_stats = categories.annotate(
        total_stock_value=Coalesce(
            ExpressionWrapper(
                F('inventory__quantity_in_Stock') * F('inventory__purchase_price'),
                output_field=DecimalField(max_digits=10, decimal_places=2)
            ),
            0,
            output_field=DecimalField(max_digits=10, decimal_places=2)
        ),
        items_count=Count('inventory', distinct=True)
    )

    # Calculate total inventory items
    total_inventory_items = Inventory.objects.count()

    context = {
        'categories': category_stats,
        'total_inventory_items': total_inventory_items
    }
    
    return render(request, 'inventory/inventory_category.html', context)


def add_inventory_category(request):
    if request.method == 'POST':
        form = Inventory_categoryForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('inventory_category')
    return render(request, 'inventory/add_inventory_category.html')

def delete_inventory_category(request, pk):
    category = get_object_or_404(Inventory_category, pk=pk)
    category.delete()
    return redirect('inventory_category')

def update_inventory_category(request, pk):
    category = get_object_or_404(Inventory_category, pk=pk)
    if request.method == 'POST':
        form = Inventory_categoryForm(request.POST, instance=category)
        if form.is_valid():
            print(form.cleaned_data)
            form.save()
            return redirect('inventory_category')
    return render(request, 'inventory/update_inventory_category.html', {'category': category})

@require_POST  # This ensures only POST requests are accepted
@login_required
def add_category_ajax(request):
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':  # Verify it's an AJAX request
        try:
            name = request.POST.get('name')
            description = request.POST.get('description')
            
            if not name:
                return JsonResponse({
                    'success': False,
                    'error': 'Category name is required'
                })
                
            category = Inventory_category.objects.create(
                name=name,
                description=description
            )
            
            return JsonResponse({
                'success': True,
                'category': {
                    'id': category.id,
                    'name': category.name
                }
            })
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            })
    
    return JsonResponse({
        'success': False,
        'error': 'Invalid request'
    })

@login_required
def inventory_update(request, pk):
    inventory = get_object_or_404(Inventory, pk=pk)
    categories = Inventory_category.objects.all()
    
    if request.method == 'POST':
        try:
            # Get form data
            data = request.POST.dict()
            data['on_sale'] = request.POST.get('on_sale') == 'on'
            
            # Get category instance
            category_id = data.pop('category', None)  # Remove category from data dict
            if category_id:
                category = get_object_or_404(Inventory_category, pk=category_id)
                inventory.category = category
            
            # Convert numeric fields
            data['purchase_price'] = Decimal(data['purchase_price'])
            data['selling_price'] = Decimal(data['selling_price'])
            data['quantity_in_Stock'] = int(data['quantity_in_Stock'])
            data['size'] = int(data.get('size', 0))
            
            # Validate prices
            if data['selling_price'] < data['purchase_price']:
                messages.error(request, "Selling price cannot be less than purchase price")
                return redirect('inventory_update', pk=pk)
            
            # Update inventory
            for key, value in data.items():
                if key not in ['csrfmiddlewaretoken']:
                    setattr(inventory, key, value)
            
            inventory.save()
            messages.success(request, f'Successfully updated {inventory.name}')
            return redirect('inventory')
            
        except (ValueError, decimal.InvalidOperation) as e:
            messages.error(request, str(e))
            return redirect('inventory_update', pk=pk)
    
    context = {
        'inventory': inventory,
        'categories': categories,
    }
    return render(request, 'inventory/inventory_update.html', context)





