from django.shortcuts import redirect, render, get_object_or_404
import plotly.utils
from .models import Return, Damaged, StockMovement, Inventory
from django.contrib.auth.decorators import login_required
from .forms import AddInventoryForm, UpdateInventoryForm, PeriodSummaryForm, DateRangeForm, ReturnInventoryForm, DamagedInventoryForm, LoginForm
from django.contrib import messages
import plotly.express as px
import pandas as pd
from django.db.models import Sum
from django.contrib.auth import login, authenticate

@login_required
def inventory_list(request):
    inventories = Inventory.objects.all()
    context = {
        'title': 'Inventory list',
        'inventories': inventories
    }
    return render(request, 'inventory/inventory_list.html', context=context)

@login_required
def per_product_view(request, pk):
    product = get_object_or_404(Inventory, pk=pk)
    context = {
        'inventory': product
    }
    return render(request, 'inventory/per_product.html', context)

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
    inventory_item = get_object_or_404(Inventory, id=pk)
    
    if request.method == 'POST':
        updateform = UpdateInventoryForm(request.POST, instance=inventory_item)
        
        if updateform.is_valid():
            print(updateform.cleaned_data)
            updated_quantity_sold = int(updateform.cleaned_data['quantity_sold'])
            sell = updateform.cleaned_data.get('sell', Decimal('0.00'))
            cost = updateform.cleaned_data.get('cost', Decimal('0.00'))

            # Ensure correct values
            sell = Decimal(sell) if sell is not None else Decimal('0.00')
            cost = Decimal(cost) if cost is not None else Decimal('0.00')

            # Calculate discount and updated cost
            discount = (sell / Decimal('100.00')) * cost
            updated_cost = cost - discount

            if inventory_item.quantity_in_Stock - updated_quantity_sold < 0:
                messages.error(request, "Not enough stock available.")
                return render(request, 'inventory/inventory_update.html', {'form': updateform})

            # Update fields
            inventory_item.name = updateform.cleaned_data['name']
            inventory_item.cost = updated_cost
            inventory_item.quantity_sold = updated_quantity_sold
            inventory_item.quantity_in_Stock -= updated_quantity_sold
            inventory_item.sales = updated_cost * updated_quantity_sold
            inventory_item.size = inventory_item.size

            # Update cumulative fields
            inventory_item.cummulative_quantity_sold += updated_quantity_sold
            inventory_item.cumulative_sales += inventory_item.sales

            inventory_item.save()
            messages.success(request, "Product successfully updated")
            return redirect('/inventory/')
        else:
            print("Form not valid")
    else:
        updateform = UpdateInventoryForm(instance=inventory_item)
    
    return render(request, 'inventory/inventory_update.html', {'form': updateform})

@login_required
def dashboard(request):
    # Get all inventory items
    inventories = Inventory.objects.all()
    
    # Convert to DataFrame
    df = pd.DataFrame(list(inventories.values()))
    
    # Best performing products (by sales)
    if not df.empty and 'name' in df.columns and 'sales' in df.columns:
        best_performing_product_df = df.nlargest(5, 'sales')[['name', 'sales']]
        best_performing_product = px.bar(
            best_performing_product_df,
            x='name',
            y='sales',
            title='Best Performing Products'
        )
        best_performing_product_html = best_performing_product.to_html()
    else:
        best_performing_product_html = "<p>No data available for best performing products</p>"

    # Most stocked products
    if not df.empty and 'name' in df.columns and 'quantity_in_Stock' in df.columns:
        most_stocked_df = df.nlargest(5, 'quantity_in_Stock')[['name', 'quantity_in_Stock']]
        most_stocked = px.bar(
            most_stocked_df,
            x='name',
            y='quantity_in_Stock',
            title='Most Stocked Products'
        )
        most_stocked_html = most_stocked.to_html()
    else:
        most_stocked_html = "<p>No data available for stocked products</p>"

    context = {
        'best_performing_product': best_performing_product_html,
        'most_stocked': most_stocked_html,
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
    else:
        sales_data = Inventory.objects.values('name').annotate(
            total_quantity_sold=Sum('quantity_sold'),
            total_sales=Sum('sales'),
            cumulative_quantity_sold=Sum('cummulative_quantity_sold'),
            cumulative_sales=Sum('cumulative_sales')
        ).order_by('name')

    context = {
        'form': form,
        'sales_data': sales_data
    }
    return render(request, 'inventory/sales_summary.html', context)

@login_required
def returnInventory(request, pk):
    inventory_item = get_object_or_404(Inventory, pk=pk)
    if request.method == 'POST':
        form = ReturnInventoryForm(request.POST)
        if form.is_valid():
            quantity_returned = form.cleaned_data['quantity_returned']
            return_instance = Return(quantity_returned=quantity_returned, inventory_item=inventory_item)
            inventory_item.quantity_in_Stock += quantity_returned
            inventory_item.save()
            return_instance.save()
            messages.success(request, f"Successfully returned {quantity_returned} item(s) of {inventory_item.name}")
            return redirect('inventory')
    else:
        form = ReturnInventoryForm()
    return render(request, 'inventory/return_inventory.html', {'form': form, 'inventory': inventory_item})

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
    inventory_item = get_object_or_404(Inventory, pk=pk)
    if request.method == 'POST':
        form = DamagedInventoryForm(request.POST)
        if form.is_valid():
            quantity_damaged = form.cleaned_data['quantity_damaged']
            damage_description = form.cleaned_data['damage_description']
            damaged_instance = Damaged(
                inventory_item=inventory_item,
                quantity_damaged=quantity_damaged,
                damage_description=damage_description
            )
            damaged_instance.save()
            inventory_item.quantity_in_Stock -= quantity_damaged
            inventory_item.save()
            messages.success(request, f"{quantity_damaged} item(s) of {inventory_item.name} successfully marked as damaged.")
            return redirect('inventory')
    else:
        form = DamagedInventoryForm()
    return render(request, 'inventory/damaged_inventory.html', {'form': form, 'inventory': inventory_item})

@login_required
def stock_movement_summary(request, pk):
    inventory_item = get_object_or_404(Inventory, pk=pk)
    stock_movements = StockMovement.objects.filter(inventory_item=inventory_item).order_by('-stock_date')
    context = {
        'inventory_item': inventory_item,
        'stock_movements': stock_movements,
    }
    return render(request, 'inventory/stock_movement_summary.html', context)

def login_view(request):
    if request.method == 'POST':
        form = LoginForm(request, data=request.POST)
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            user = authenticate(username=username, password=password)
            if user is not None:
                login(request, user)
                messages.success(request, f'Welcome back {username}!')
                return redirect('inventory')  # or wherever you want to redirect after login
            else:
                messages.error(request, 'Invalid username or password.')
        else:
            messages.error(request, 'Invalid username or password.')
    else:
        form = LoginForm()
    return render(request, 'inventory_system/login.html', {'form': form})

@login_required
def add_inventory(request):
    if request.method == 'POST':
        form = AddInventoryForm(request.POST)
        if form.is_valid():
            inventory = form.save()
            messages.success(request, f'Product "{inventory.name}" has been added successfully!')
            return redirect('inventory')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = AddInventoryForm()
    return render(request, 'inventory/inventory_add.html', {'form': form})

@login_required
def update_inventory(request, pk):
    inventory_item = get_object_or_404(Inventory, id=pk)
    if request.method == 'POST':
        form = UpdateInventoryForm(request.POST, instance=inventory_item)
        if form.is_valid():
            updated_item = form.save()
            messages.success(request, f'Sale recorded for "{updated_item.name}"!')
            return redirect('inventory')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = UpdateInventoryForm(instance=inventory_item)
    return render(request, 'inventory/inventory_update.html', {'form': form})

@login_required
def return_inventory(request, pk):
    inventory_item = get_object_or_404(Inventory, id=pk)
    if request.method == 'POST':
        form = ReturnInventoryForm(request.POST)
        if form.is_valid():
            return_item = form.save(commit=False)
            return_item.inventory = inventory_item
            return_item.save()
            messages.success(request, f'Return recorded for "{inventory_item.name}"')
            return redirect('inventory')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = ReturnInventoryForm()
    return render(request, 'inventory/return.html', {'form': form, 'inventory': inventory_item})

@login_required
def damaged_inventory(request, pk):
    inventory_item = get_object_or_404(Inventory, id=pk)
    if request.method == 'POST':
        form = DamagedInventoryForm(request.POST)
        if form.is_valid():
            damaged_item = form.save(commit=False)
            damaged_item.inventory = inventory_item
            damaged_item.save()
            messages.success(request, f'Damage recorded for "{inventory_item.name}"')
            return redirect('inventory')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = DamagedInventoryForm()
    return render(request, 'inventory/damaged.html', {'form': form, 'inventory': inventory_item})

