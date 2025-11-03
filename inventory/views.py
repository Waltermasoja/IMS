from django.shortcuts import redirect, render,get_object_or_404
import plotly.utils
from .models import Inventory, Return, Damaged, StockMovement, Sales, missing_inventory, Inventory_category
from django.contrib.auth.decorators import login_required
from .forms import (
    AddInventoryForm,
    UpdateInventoryForm,
    DateRangeForm,
    ReturnInventoryForm,
    DamagedInventoryForm,
    Inventory_categoryForm,
    SupplierForm,
    ImportOrderForm,
    ImportExpenseForm,
    ImportExpenseFormSet,
    ImportOrderItemFormSet,
    SupplierInvoiceForm,
    InvoicePaymentForm,
    ExpenseAllocationForm,
    CustomerForm,
)
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
from .models import (
    Inventory,
    Sales,
    Return,
    Damaged,
    Inventory_category,
    Supplier,
    ImportOrder,
    SupplierInvoice,
    InvoicePayment,
    ImportExpense,
    ImportOrderItem,
    Customer,
)
from .utils import run_allocation
import json
import calendar
from django.urls import reverse
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.http import require_http_methods
import decimal
from django.template.loader import render_to_string
from django.core.mail import send_mail
from django.http import HttpResponse
import csv


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
@require_http_methods(["POST"])
def make_sale(request, pk):
    """Process a sale for a specific inventory item.
    Supports payment_method: CASH (default), CREDIT, LAYBY.
    For CREDIT: requires customer_id and due_date; creates ARInvoice.
    For LAYBY: requires customer_id and deposit(optional); creates LaybyPlan and reserves stock.
    """
    inventory = get_object_or_404(Inventory, pk=pk)
    
    try:
        with transaction.atomic():
            quantity_sold = int(request.POST.get('quantity_sold'))
            sale_price = Decimal(request.POST.get('sale_price'))
            discount = Decimal(request.POST.get('discount_applied', 0))
            payment_method = request.POST.get('payment_method', 'CASH').upper()
            customer_id = request.POST.get('customer_id')
            due_date_str = request.POST.get('due_date')
            deposit = Decimal(request.POST.get('deposit', '0') or '0')

            # Validation
            if quantity_sold <= 0:
                return JsonResponse({
                    'success': False,
                    'error': 'Quantity must be greater than 0'
                })
            
            if quantity_sold > inventory.quantity_in_Stock:
                return JsonResponse({
                    'success': False,
                    'error': f'Not enough stock. Available: {inventory.quantity_in_Stock}'
                })
            
            if sale_price <= 0:
                return JsonResponse({
                    'success': False,
                    'error': 'Sale price must be greater than 0'
                })
            
            if discount < 0 or discount > 100:
                return JsonResponse({
                    'success': False,
                    'error': 'Discount must be between 0 and 100%'
                })

            # Calculate total amount
            discounted_price = sale_price * (1 - discount / 100)
            total_amount = discounted_price * quantity_sold

            # Validate stock for all methods
            if quantity_sold > inventory.quantity_in_Stock:
                return JsonResponse({'success': False, 'error': f'Not enough stock. Available: {inventory.quantity_in_Stock}'})

            if payment_method == 'CREDIT':
                # Validate customer and due date
                if not customer_id or not due_date_str:
                    return JsonResponse({'success': False, 'error': 'customer_id and due_date are required for CREDIT sales'})
                from .models import Customer, ARInvoice
                customer = get_object_or_404(Customer, pk=customer_id)

                # Authorize within limit
                if customer.current_balance + total_amount > customer.credit_limit:
                    return JsonResponse({'success': False, 'error': 'Credit limit exceeded'})

                # Reduce stock and record movement
                inventory.quantity_in_Stock -= quantity_sold
                inventory.last_sale_date = timezone.now()
                inventory.save()
                StockMovement.objects.create(
                    inventory_item=inventory,
                    movement_type='OUT',
                    quantity=quantity_sold,
                    reason='Credit sale (on account)'
                )

                # Create sales record (delivered)
                receipt_number = f"R{timezone.now().strftime('%Y%m%d%H%M%S')}"
                sale = Sales.objects.create(
                    inventory_item=inventory,
                    quantity_sold=quantity_sold,
                    sale_price=sale_price,
                    discount_applied=discount,
                    total_amount=total_amount,
                    receipt_number=receipt_number,
                    sale_date=timezone.now(),
                    recorded_by=request.user,
                    payment_method='CREDIT',
                    customer=customer
                )

                # Post Journal: Dr A/R, Cr Sales AND Dr COGS, Cr Inventory
                try:
                    from .models import GLAccount, JournalEntry, JournalLine
                    ar_acct = GLAccount.objects.get(code='1200')
                    sales_acct = GLAccount.objects.get(code='4000')
                    cogs_acct = GLAccount.objects.get(code='5000')
                    inventory_acct = GLAccount.objects.get(code='1500')
                    
                    je = JournalEntry.objects.create(memo='Credit sale')
                    # Revenue side
                    JournalLine.objects.create(entry=je, account=ar_acct, debit=total_amount, description='Accounts receivable', customer=customer)
                    JournalLine.objects.create(entry=je, account=sales_acct, credit=total_amount, description='Sales revenue')
                    # COGS side
                    cogs_amount = inventory.purchase_price * quantity_sold
                    JournalLine.objects.create(entry=je, account=cogs_acct, debit=cogs_amount, description='Cost of goods sold')
                    JournalLine.objects.create(entry=je, account=inventory_acct, credit=cogs_amount, description='Inventory reduction')
                except Exception:
                    pass

                # Create AR invoice
                from datetime import datetime as dt
                due_date = dt.strptime(due_date_str, '%Y-%m-%d').date()
                inv_no = f"AR{timezone.now().strftime('%Y%m%d%H%M%S')}"
                ar = ARInvoice.objects.create(
                    customer=customer,
                    invoice_number=inv_no,
                    invoice_date=timezone.now().date(),
                    due_date=due_date,
                    total_amount=total_amount,
                    sale=sale
                )
                # Update customer balance
                customer.current_balance = (customer.current_balance or Decimal('0')) + total_amount
                customer.save(update_fields=['current_balance'])

                return JsonResponse({
                    'success': True,
                    'message': f'Credit sale recorded. AR Invoice: {ar.invoice_number}',
                    'invoice_number': ar.invoice_number,
                    'total_amount': str(total_amount),
                    'remaining_stock': inventory.quantity_in_Stock
                })

            if payment_method == 'LAYBY':
                if not customer_id:
                    return JsonResponse({'success': False, 'error': 'customer_id is required for LAYBY'})
                from .models import Customer, LaybyPlan, LaybyItem, LaybyPayment
                customer = get_object_or_404(Customer, pk=customer_id)

                # Reserve stock now
                inventory.quantity_in_Stock -= quantity_sold
                inventory.save()
                StockMovement.objects.create(
                    inventory_item=inventory,
                    movement_type='OUT',
                    quantity=quantity_sold,
                    reason='Layby reserve'
                )

                plan = LaybyPlan.objects.create(
                    customer=customer,
                    deposit_amount=deposit,
                    total_price=total_amount,
                )
                # Record a non-fulfilled layby sale shell (optional): we skip creating a Sales row now to avoid recognizing revenue
                LaybyItem.objects.create(
                    plan=plan,
                    inventory_item=inventory,
                    quantity=quantity_sold,
                    unit_price=discounted_price,
                )
                if deposit and deposit > 0:
                    LaybyPayment.objects.create(
                        plan=plan,
                        amount=deposit,
                        recorded_by=request.user,
                    )
                return JsonResponse({
                    'success': True,
                    'message': f'Layby plan created: #{plan.id}',
                    'layby_plan_id': plan.id,
                    'total_price': str(total_amount),
                    'deposit': str(deposit),
                    'remaining_stock': inventory.quantity_in_Stock
                })

            # Default: CASH sale
            # Post Journal: Dr Cash, Cr Sales AND Dr COGS, Cr Inventory
            try:
                from .models import GLAccount, JournalEntry, JournalLine
                cash = GLAccount.objects.get(code='1000')
                sales_acct = GLAccount.objects.get(code='4000')
                cogs_acct = GLAccount.objects.get(code='5000')
                inventory_acct = GLAccount.objects.get(code='1500')
                
                je = JournalEntry.objects.create(memo='Cash sale')
                # Revenue side
                JournalLine.objects.create(entry=je, account=cash, debit=total_amount, description='Cash received')
                JournalLine.objects.create(entry=je, account=sales_acct, credit=total_amount, description='Sales revenue')
                # COGS side
                cogs_amount = inventory.purchase_price * quantity_sold
                JournalLine.objects.create(entry=je, account=cogs_acct, debit=cogs_amount, description='Cost of goods sold')
                JournalLine.objects.create(entry=je, account=inventory_acct, credit=cogs_amount, description='Inventory reduction')
            except Exception:
                pass
            # Generate receipt number
            receipt_number = f"R{timezone.now().strftime('%Y%m%d%H%M%S')}"

            # Create sales record
            customer_obj = None
            if customer_id:
                try:
                    from .models import Customer as Cust
                    customer_obj = Cust.objects.get(pk=customer_id)
                except Cust.DoesNotExist:
                    customer_obj = None
            sale = Sales.objects.create(
                inventory_item=inventory,
                quantity_sold=quantity_sold,
                sale_price=sale_price,
                discount_applied=discount,
                total_amount=total_amount,
                receipt_number=receipt_number,
                sale_date=timezone.now(),
                recorded_by=request.user,
                payment_method='CASH',
                customer=customer_obj
            )

            # Update inventory stock
            inventory.quantity_in_Stock -= quantity_sold
            inventory.last_sale_date = timezone.now()
            inventory.save()

            # Create stock movement record
            StockMovement.objects.create(
                inventory_item=inventory,
                movement_type='OUT',
                quantity=quantity_sold,
                reason=f'Sale (Receipt: {receipt_number})'
            )

            # Cashbook receipt for CASH sales
            try:
                CashbookEntry.objects.create(
                    date=timezone.now().date(),
                    reference=receipt_number,
                    description=f"Cash sale - {inventory.name}",
                    receipt_amount=total_amount,
                    payment_amount=0,
                    category='SALES',
                    recorded_by=request.user,
                )
            except Exception:
                pass

            return JsonResponse({
                'success': True,
                'message': f'Sale completed successfully! Receipt: {receipt_number}',
                'receipt_number': receipt_number,
                'total_amount': str(total_amount),
                'remaining_stock': inventory.quantity_in_Stock
            })

    except (ValueError, TypeError, decimal.InvalidOperation) as e:
        return JsonResponse({
            'success': False,
            'error': 'Invalid input values. Please check your entries.'
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'An error occurred: {str(e)}'
        })





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
def sales_report_simple(request):
    from django.utils import timezone as tz
    from datetime import timedelta
    start = (tz.now() - timedelta(days=30)).date()
    qs = Sales.objects.filter(sale_date__date__gte=start)

    # totals by method
    methods = ['CASH','CREDIT','LAYBY']
    totals_by_method = {m: float(qs.filter(payment_method=m).aggregate(total=Sum('total_amount'))['total'] or 0) for m in methods}

    # daily rows
    daily_rows = []
    for i in range(30, -1, -1):
        day = (tz.now() - timedelta(days=i)).date()
        row = {
            'date': day,
            'cash': float(qs.filter(sale_date__date=day, payment_method='CASH').aggregate(total=Sum('total_amount'))['total'] or 0),
            'credit': float(qs.filter(sale_date__date=day, payment_method='CREDIT').aggregate(total=Sum('total_amount'))['total'] or 0),
            'layby': float(qs.filter(sale_date__date=day, payment_method='LAYBY').aggregate(total=Sum('total_amount'))['total'] or 0),
        }
        row['total'] = row['cash'] + row['credit'] + row['layby']
        daily_rows.append(row)

    return render(request, 'inventory/sales_report_simple.html', {
        'totals_by_method': totals_by_method,
        'daily_rows': daily_rows,
    })

# ===== Simple endpoints to manage Customers, AR, Layby =====
@login_required
def ar_list(request):
    invoices = ARInvoice.objects.select_related('customer').order_by('due_date')
    total_outstanding = sum([inv.outstanding_amount for inv in invoices])
    overdue = [inv for inv in invoices if inv.is_overdue]
    partial = [inv for inv in invoices if inv.status == 'PARTIAL']
    from django.utils import timezone
    today = timezone.now().date().isoformat()
    return render(request, 'inventory/ar_list.html', {
        'invoices': invoices,
        'total_outstanding': total_outstanding,
        'overdue_count': len(overdue),
        'invoice_count': invoices.count(),
        'partial_count': len(partial),
        'today': today,
    })

@login_required
def layby_list(request):
    plans = LaybyPlan.objects.select_related('customer').order_by('-created_date')
    total_remaining = sum([(p.remaining or 0) for p in plans])
    active_count = plans.filter(status='ACTIVE').count()
    fulfilled_count = plans.filter(status='FULFILLED').count()
    from django.utils import timezone
    today = timezone.now().date().isoformat()
    return render(request, 'inventory/layby_list.html', {
        'plans': plans,
        'total_remaining': total_remaining,
        'active_count': active_count,
        'fulfilled_count': fulfilled_count,
        'today': today,
    })
@login_required
def customers_list(request):
    customers = Customer.objects.all().order_by('name')
    active_count = customers.filter(status='ACTIVE').count()
    suspended_count = customers.filter(status='SUSPENDED').count()
    inactive_count = customers.filter(status='INACTIVE').count()
    total_balance = customers.aggregate(total=Sum('current_balance'))['total'] or 0
    return render(request, 'inventory/customers_list.html', {
        'customers': customers,
        'active_count': active_count,
        'suspended_count': suspended_count,
        'inactive_count': inactive_count,
        'total_balance': total_balance,
    })

@login_required
def customer_create(request):
    if request.method == 'POST':
        form = CustomerForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Customer created')
            return redirect('customers_list')
    else:
        form = CustomerForm()
    return render(request, 'inventory/customer_form.html', {'form': form, 'title': 'Add Customer'})

@login_required
@require_POST
def customer_create_ajax(request):
    form = CustomerForm(request.POST)
    if form.is_valid():
        customer = form.save()
        return JsonResponse({
            'success': True,
            'customer': {
                'id': customer.id,
                'name': customer.name,
                'phone': customer.phone,
                'email': customer.email,
                'credit_limit': str(customer.credit_limit),
                'status': customer.status,
            }
        })
    return JsonResponse({'success': False, 'errors': form.errors}, status=400)

@login_required
def customer_update(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    if request.method == 'POST':
        form = CustomerForm(request.POST, instance=customer)
        if form.is_valid():
            form.save()
            messages.success(request, 'Customer updated')
            return redirect('customers_list')
    else:
        form = CustomerForm(instance=customer)
    return render(request, 'inventory/customer_form.html', {'form': form, 'title': 'Edit Customer'})

@login_required
@require_POST
def ar_payment_create(request):
    form = ARPaymentFormSimple(request.POST)
    if form.is_valid():
        payment = form.save(commit=False)
        payment.recorded_by = request.user
        payment.save()
        messages.success(request, 'A/R payment recorded')
        return redirect('dashboard')
    messages.error(request, 'Invalid payment data')
    return redirect('dashboard')

@login_required
@require_POST
def layby_payment_create(request):
    form = LaybyPaymentFormSimple(request.POST)
    if form.is_valid():
        payment = form.save(commit=False)
        payment.recorded_by = request.user
        payment.save()
        messages.success(request, 'Layby payment recorded')
        return redirect('dashboard')
    messages.error(request, 'Invalid layby payment data')
    return redirect('dashboard')

@login_required
@require_POST
def layby_fulfill(request, pk):
    from .models import LaybyPlan, GLAccount, JournalEntry, JournalLine
    plan = get_object_or_404(LaybyPlan, pk=pk)
    if plan.status != 'ACTIVE':
        messages.error(request, 'Plan not active')
        return redirect('dashboard')
    # Recognize revenue: Dr Unearned, Cr Sales for total_price AND Dr COGS, Cr Inventory
    try:
        unearned = GLAccount.objects.get(code='2300')
        sales_acct = GLAccount.objects.get(code='4000')
        cogs_acct = GLAccount.objects.get(code='5000')
        inventory_acct = GLAccount.objects.get(code='1500')
        
        je = JournalEntry.objects.create(memo=f'Layby fulfill plan#{plan.id}')
        # Revenue recognition
        JournalLine.objects.create(entry=je, account=unearned, debit=plan.total_price, description='Recognize revenue')
        JournalLine.objects.create(entry=je, account=sales_acct, credit=plan.total_price, description='Sales revenue')
        # COGS for all layby items
        total_cogs = Decimal('0')
        for item in plan.items.select_related('inventory_item'):
            cogs_amount = item.inventory_item.purchase_price * item.quantity
            total_cogs += cogs_amount
        if total_cogs > 0:
            JournalLine.objects.create(entry=je, account=cogs_acct, debit=total_cogs, description='Cost of goods sold')
            JournalLine.objects.create(entry=je, account=inventory_acct, credit=total_cogs, description='Inventory reduction')
    except GLAccount.DoesNotExist:
        pass
    plan.status = 'FULFILLED'
    plan.save(update_fields=['status'])
    messages.success(request, 'Layby fulfilled')
    return redirect('dashboard')

@login_required
@require_POST
def layby_cancel(request, pk):
    from .models import LaybyPlan, GLAccount, JournalEntry, JournalLine
    plan = get_object_or_404(LaybyPlan, pk=pk)
    fee = Decimal(request.POST.get('cancellation_fee', '0') or '0')
    # Restock inventory for each item
    for item in plan.items.select_related('inventory_item'):
        inv = item.inventory_item
        inv.quantity_in_Stock += item.quantity
        inv.save(update_fields=['quantity_in_Stock'])
        StockMovement.objects.create(inventory_item=inv, movement_type='IN', quantity=item.quantity, reason=f'Layby cancel plan#{plan.id}')
    # Journal: refund = amount_paid - fee; Dr Unearned Cr Cash (refund); Dr Unearned Cr OtherIncome (fee)
    refund = max(Decimal('0'), (plan.amount_paid or Decimal('0')) - fee)
    try:
        unearned = GLAccount.objects.get(code='2300')
        cash = GLAccount.objects.get(code='1000')
        je = JournalEntry.objects.create(memo=f'Layby cancel plan#{plan.id}')
        if refund > 0:
            JournalLine.objects.create(entry=je, account=unearned, debit=refund, description='Refund customer')
            JournalLine.objects.create(entry=je, account=cash, credit=refund, description='Cash out')
        if fee > 0:
            other_income = GLAccount.objects.get(code='4800')
            JournalLine.objects.create(entry=je, account=unearned, debit=fee, description='Forfeit fee')
            JournalLine.objects.create(entry=je, account=other_income, credit=fee, description='Layby forfeit income')
    except GLAccount.DoesNotExist:
        pass
    plan.status = 'CANCELLED'
    plan.save(update_fields=['status'])
    messages.success(request, 'Layby cancelled')
    return redirect('dashboard')


@login_required
def sales_summary(request):
    form = DateRangeForm(request.GET or None)
    sales = Sales.objects.all().order_by('-sale_date')

    # If user is a sales person, show only their sales
    is_my_sales = False
    if hasattr(request.user, 'profile') and request.user.profile.is_sales_person:
        sales = sales.filter(recorded_by=request.user)
        is_my_sales = True
    
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
        'is_my_sales': is_my_sales,
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
    
    # Also include damages data
    damages = Damaged.objects.all() 
    total_damages = damages.aggregate(total_quantity_damaged=Sum('quantity_damaged'))

    context = {
        'returns':returns,
        'total_returns':total_returns,
        'damages': damages,
        'total_damages': total_damages
    }
    return render(request,'inventory/return_summary.html',context)


@login_required
def obsolate_summary(request):
    damages = Damaged.objects.all() 
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





@login_required
def suppliers_list(request):
    suppliers = Supplier.objects.all().order_by('name')
    return render(request, 'inventory/suppliers_list.html', {
        'suppliers': suppliers,
    })


@login_required
def supplier_create(request):
    if request.method == 'POST':
        form = SupplierForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Supplier created successfully')
            return redirect('suppliers_list')
    else:
        form = SupplierForm()
    return render(request, 'inventory/supplier_form.html', {'form': form, 'title': 'Add Supplier'})


@login_required
def supplier_update(request, pk):
    supplier = get_object_or_404(Supplier, pk=pk)
    if request.method == 'POST':
        form = SupplierForm(request.POST, instance=supplier)
        if form.is_valid():
            form.save()
            messages.success(request, 'Supplier updated successfully')
            return redirect('suppliers_list')
    else:
        form = SupplierForm(instance=supplier)
    return render(request, 'inventory/supplier_form.html', {'form': form, 'title': 'Edit Supplier'})


@login_required
def import_orders_list(request):
    orders = ImportOrder.objects.select_related('supplier').order_by('-order_date')
    return render(request, 'inventory/import_orders_list.html', {'orders': orders})


@login_required
def import_order_create(request):
    if request.method == 'POST':
        form = ImportOrderForm(request.POST)
        if form.is_valid():
            import_order = form.save(commit=False)
            import_order.created_by = request.user
            import_order.save()
            messages.success(request, f'Import order {import_order.order_number} created')
            return redirect('import_order_detail', pk=import_order.pk)
    else:
        form = ImportOrderForm()
    return render(request, 'inventory/import_order_form.html', {'form': form})


@login_required
def import_order_detail(request, pk):
    import_order = get_object_or_404(ImportOrder.objects.select_related('supplier'), pk=pk)
    items_formset = ImportOrderItemFormSet(instance=import_order)
    expenses_formset = ImportExpenseFormSet(instance=import_order)

    if request.method == 'POST':
        if 'save_items' in request.POST:
            items_formset = ImportOrderItemFormSet(request.POST, instance=import_order)
            if items_formset.is_valid():
                items_formset.save()
                messages.success(request, 'Order items saved')
                return redirect('import_order_detail', pk=pk)
            else:
                messages.error(request, 'Please fix errors in the items form')
        elif 'save_expenses' in request.POST:
            expenses_formset = ImportExpenseFormSet(request.POST, instance=import_order)
            if expenses_formset.is_valid():
                expenses_formset.save()
                messages.success(request, 'Order expenses saved')
                return redirect('import_order_detail', pk=pk)
            else:
                messages.error(request, 'Please fix errors in the expenses form')

    invoices = SupplierInvoice.objects.filter(import_order=import_order)

    return render(request, 'inventory/import_order_detail.html', {
        'order': import_order,
        'items_formset': items_formset,
        'expenses_formset': expenses_formset,
        'invoices': invoices,
    })


@login_required
@require_POST
def import_order_allocate(request, pk):
    import_order = get_object_or_404(ImportOrder, pk=pk)
    try:
        success = run_allocation(import_order)
        if success:
            messages.success(request, 'Expenses allocated and prices updated')
        else:
            messages.warning(request, 'Allocation did not run. Ensure items and expenses are present.')
    except Exception as e:
        messages.error(request, f'Allocation error: {str(e)}')
    return redirect('import_order_detail', pk=pk)


@login_required
@require_POST
def import_order_bulk_upload(request, pk):
    """Handle CSV bulk upload for import order items"""
    import_order = get_object_or_404(ImportOrder, pk=pk)
    
    if 'csv_file' not in request.FILES:
        messages.error(request, 'No file uploaded')
        return redirect('import_order_detail', pk=pk)
    
    csv_file = request.FILES['csv_file']
    
    # Validate file
    from .bulk_import import validate_csv_file, parse_csv_for_import
    is_valid, error_msg = validate_csv_file(csv_file)
    
    if not is_valid:
        messages.error(request, f'File validation failed: {error_msg}')
        return redirect('import_order_detail', pk=pk)
    
    # Parse and create items
    success_count, errors = parse_csv_for_import(csv_file, import_order)
    
    if success_count > 0:
        messages.success(request, f'Successfully imported {success_count} products')
    
    if errors:
        error_summary = '<br>'.join(errors[:5])  # Show first 5 errors
        if len(errors) > 5:
            error_summary += f'<br>...and {len(errors) - 5} more errors'
        messages.warning(request, f'Import completed with errors:<br>{error_summary}')
    
    return redirect('import_order_detail', pk=pk)


@login_required
def download_csv_template(request):
    """Download CSV template for bulk import"""
    from django.http import HttpResponse
    from .bulk_import import generate_csv_template
    
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="import_template.csv"'
    response.write(generate_csv_template())
    
    return response


@login_required
@require_POST
def import_order_receive_goods(request, pk):
    """Receive all goods from import order and update stock"""
    import_order = get_object_or_404(ImportOrder, pk=pk)
    
    try:
        items_received = import_order.receive_all_goods()
        messages.success(request, f'Successfully received {items_received} items. Stock has been updated.')
        
        # Show new product codes
        new_products = import_order.created_products.all()
        if new_products.exists():
            product_codes = ', '.join([p.product_code for p in new_products[:5]])
            if new_products.count() > 5:
                product_codes += f' and {new_products.count() - 5} more'
            messages.info(request, f'New products created: {product_codes}')
    
    except Exception as e:
        messages.error(request, f'Error receiving goods: {str(e)}')
    
    return redirect('import_order_detail', pk=pk)


@login_required
def add_supplier_invoice(request, pk):
    import_order = get_object_or_404(ImportOrder, pk=pk)
    if request.method == 'POST':
        form = SupplierInvoiceForm(request.POST, import_order=import_order)
        if form.is_valid():
            invoice = form.save(commit=False)
            invoice.import_order = import_order
            invoice.save()
            messages.success(request, f'Invoice {invoice.invoice_number} added')
            return redirect('import_order_detail', pk=pk)
    else:
        form = SupplierInvoiceForm(import_order=import_order)
    return render(request, 'inventory/invoice_form.html', {'form': form, 'order': import_order})


@login_required
def add_invoice_payment(request, pk):
    invoice = get_object_or_404(SupplierInvoice, pk=pk)
    if request.method == 'POST':
        form = InvoicePaymentForm(request.POST)
        if form.is_valid():
            payment = form.save(commit=False)
            payment.invoice = invoice
            payment.recorded_by = request.user
            payment.save()
            messages.success(request, 'Payment recorded')
            return redirect('import_order_detail', pk=invoice.import_order_id)
    else:
        form = InvoicePaymentForm()
    return render(request, 'inventory/payment_form.html', {'form': form, 'invoice': invoice})


@login_required
def pos_interface(request):
    """Point of Sale interface for sales personnel"""
    # Check if user has profile, create if not exists
    if not hasattr(request.user, 'profile'):
        from .models import UserProfile
        UserProfile.objects.create(
            user=request.user,
            role='admin' if request.user.is_staff else 'sales'
        )
    
    # Check POS access permission
    if not request.user.profile.can_access_pos:
        messages.error(request, 'You do not have permission to access the Point of Sale system.')
        return redirect('dashboard')
    
    customers = Customer.objects.all().order_by('name')
    context = {
        'user_role': request.user.profile.role,
        'max_discount': request.user.profile.max_discount_percent,
        'customers': customers,
    }
    
    return render(request, 'inventory/simple_pos.html', context)




@login_required
def sales_report_detailed(request):
    """Detailed sales report with filters and breakdowns by salesperson and product."""
    form = DateRangeForm(request.GET or None)

    qs = Sales.objects.select_related('inventory_item', 'recorded_by').all()

    # Filters
    if form.is_valid():
        start_date = form.cleaned_data.get('start_date')
        end_date = form.cleaned_data.get('end_date')
        if start_date:
            qs = qs.filter(sale_date__date__gte=start_date)
        if end_date:
            qs = qs.filter(sale_date__date__lte=end_date)

    payment_method = request.GET.get('payment_method')
    if payment_method:
        qs = qs.filter(payment_method=payment_method.upper())

    salesperson_id = request.GET.get('salesperson')
    if salesperson_id:
        qs = qs.filter(recorded_by_id=salesperson_id)

    product_id = request.GET.get('product')
    if product_id:
        qs = qs.filter(inventory_item_id=product_id)

    # Aggregations
    by_user = (
        qs.values('recorded_by__id', 'recorded_by__username')
          .annotate(
              total_amount=Sum('total_amount'),
              total_qty=Sum('quantity_sold'),
              total_returns=Sum('quantity_returned'),
              cogs=Sum(ExpressionWrapper(F('inventory_item__purchase_price') * F('quantity_sold'), output_field=DecimalField(max_digits=15, decimal_places=2)))
          )
          .order_by('-total_amount')
    )

    by_product = (
        qs.values('inventory_item__id', 'inventory_item__name')
          .annotate(
              total_amount=Sum('total_amount'),
              total_qty=Sum('quantity_sold'),
              total_returns=Sum('quantity_returned'),
              cogs=Sum(ExpressionWrapper(F('inventory_item__purchase_price') * F('quantity_sold'), output_field=DecimalField(max_digits=15, decimal_places=2)))
          )
          .order_by('-total_amount')
    )

    totals = {
        'amount': qs.aggregate(t=Sum('total_amount'))['t'] or 0,
        'qty': qs.aggregate(t=Sum('quantity_sold'))['t'] or 0,
        'returns': qs.aggregate(t=Sum('quantity_returned'))['t'] or 0,
        'cogs': qs.aggregate(t=Sum(ExpressionWrapper(F('inventory_item__purchase_price') * F('quantity_sold'), output_field=DecimalField(max_digits=15, decimal_places=2))))['t'] or 0,
    }

    # Distinct lists for filters
    salespeople = (Sales.objects.exclude(recorded_by=None)
                   .values('recorded_by__id', 'recorded_by__username')
                   .distinct().order_by('recorded_by__username'))
    products = (Sales.objects.values('inventory_item__id', 'inventory_item__name')
                .distinct().order_by('inventory_item__name'))

    # Recent detailed rows (limited)
    details = qs.order_by('-sale_date')[:200]

    context = {
        'form': form,
        'by_user': by_user,
        'by_product': by_product,
        'totals': totals,
        'salespeople': salespeople,
        'products': products,
        'details': details,
        'selected': {
            'payment_method': payment_method or '',
            'salesperson': salesperson_id or '',
            'product': product_id or '',
        }
    }

    return render(request, 'inventory/sales_report_detailed.html', context)


@login_required
def sales_report_export_csv(request):
    """CSV export for detailed sales report with same filters as sales_report_detailed."""
    form = DateRangeForm(request.GET or None)
    qs = Sales.objects.select_related('inventory_item', 'recorded_by').all()

    if form.is_valid():
        start_date = form.cleaned_data.get('start_date')
        end_date = form.cleaned_data.get('end_date')
        if start_date:
            qs = qs.filter(sale_date__date__gte=start_date)
        if end_date:
            qs = qs.filter(sale_date__date__lte=end_date)

    payment_method = request.GET.get('payment_method')
    if payment_method:
        qs = qs.filter(payment_method=payment_method.upper())

    salesperson_id = request.GET.get('salesperson')
    if salesperson_id:
        qs = qs.filter(recorded_by_id=salesperson_id)

    product_id = request.GET.get('product')
    if product_id:
        qs = qs.filter(inventory_item_id=product_id)

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="sales_report.csv"'

    writer = csv.writer(response)
    writer.writerow(['Date', 'Receipt', 'Product', 'Qty', 'Unit Price', 'Discount %', 'Total', 'Payment Method', 'Salesperson'])

    for s in qs.order_by('sale_date'):
        writer.writerow([
            s.sale_date.strftime('%Y-%m-%d %H:%M'),
            s.receipt_number or '',
            s.inventory_item.name if s.inventory_item_id else '',
            s.quantity_sold,
            f"{s.sale_price}",
            f"{s.discount_applied}",
            f"{s.total_amount}",
            s.payment_method,
            s.recorded_by.username if s.recorded_by_id else ''
        ])

    return response
@login_required
@require_http_methods(["GET"])
def product_search_ajax(request):
    """AJAX endpoint for fast product search by common fields"""
    query = request.GET.get('q', '').strip()

    if not query:
        return JsonResponse({'products': []})

    # Broaden search: product_code, name, label, category name, and size
    products = (
        Inventory.objects.filter(
            Q(product_code__icontains=query)
            | Q(name__icontains=query)
            | Q(label__icontains=query)
            | Q(size__icontains=query)
            | Q(category__name__icontains=query)
        )
        .select_related('category')
        .order_by('product_code')[:10]
    )

    results = []
    for product in products:
        results.append({
            'id': product.id,
            'product_code': product.product_code,
            'name': product.name,
            'label': product.label,
            'selling_price': str(product.selling_price),
            'quantity_in_stock': product.quantity_in_Stock,
            'category': product.category.name if product.category else 'Uncategorized',
            'display_name': f"{product.product_code} - {product.name}"
        })

    return JsonResponse({'products': results})


@login_required
@require_http_methods(["GET"])
def invoice_print(request, receipt_number):
    """Printable invoice view grouping all sales by a receipt number."""
    sales = (Sales.objects
             .select_related('inventory_item', 'customer')
             .filter(receipt_number=receipt_number)
             .order_by('sale_date'))
    if not sales.exists():
        return render(request, 'inventory/invoice_print.html', {
            'not_found': True,
            'receipt_number': receipt_number,
        })

    # Aggregate totals and simple line items
    line_items = []
    subtotal = Decimal('0')
    discount_total = Decimal('0')
    for s in sales:
        line_total = s.total_amount
        line_items.append({
            'name': s.inventory_item.name,
            'qty': s.quantity_sold,
            'unit_price': s.sale_price,
            'discount_percent': s.discount_applied,
            'line_total': line_total,
        })
        subtotal += (s.sale_price * s.quantity_sold)
        # discount_applied is percent per line
        discount_total += (s.sale_price * s.quantity_sold) * (s.discount_applied / 100)

    total_amount = sum((s.total_amount for s in sales), Decimal('0'))
    customer = sales.first().customer

    context = {
        'receipt_number': receipt_number,
        'customer': customer,
        'sales': sales,
        'line_items': line_items,
        'subtotal': subtotal,
        'discount_total': discount_total,
        'total_amount': total_amount,
        'sale_date': sales.first().sale_date,
    }
    return render(request, 'inventory/invoice_print.html', context)


def render_invoice_html(receipt_number):
    sales = (Sales.objects
             .select_related('inventory_item', 'customer')
             .filter(receipt_number=receipt_number)
             .order_by('sale_date'))
    if not sales.exists():
        return render_to_string('inventory/invoice_print.html', {
            'not_found': True,
            'receipt_number': receipt_number,
        })
    from decimal import Decimal as D
    line_items = []
    subtotal = D('0')
    discount_total = D('0')
    for s in sales:
        line_items.append({
            'name': s.inventory_item.name,
            'qty': s.quantity_sold,
            'unit_price': s.sale_price,
            'discount_percent': s.discount_applied,
            'line_total': s.total_amount,
        })
        subtotal += (s.sale_price * s.quantity_sold)
        discount_total += (s.sale_price * s.quantity_sold) * (s.discount_applied / 100)
    total_amount = sum((s.total_amount for s in sales), D('0'))
    html = render_to_string('inventory/invoice_print.html', {
        'receipt_number': receipt_number,
        'customer': sales.first().customer,
        'sales': sales,
        'line_items': line_items,
        'subtotal': subtotal,
        'discount_total': discount_total,
        'total_amount': total_amount,
        'sale_date': sales.first().sale_date,
    })
    return html

@login_required
@require_http_methods(["GET"])
def product_details_ajax(request, pk):
    """Get detailed product information for sales modal"""
    try:
        product = Inventory.objects.select_related('category').get(pk=pk)
        
        data = {
            'id': product.id,
            'product_code': product.product_code,
            'name': product.name,
            'label': product.label,
            'selling_price': str(product.selling_price),
            'quantity_in_stock': product.quantity_in_Stock,
            'category': product.category.name if product.category else 'Uncategorized',
            'description': product.description,
            'size': product.size,
            'on_sale': product.on_sale
        }
        
        return JsonResponse({'success': True, 'product': data})
        
    except Inventory.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Product not found'})


