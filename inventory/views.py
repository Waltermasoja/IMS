import logging
from django.shortcuts import redirect, render,get_object_or_404

logger = logging.getLogger(__name__)
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
    SiteSettingsForm,
    ProductWithVariantsForm,
    VariantAttributeSelectionForm,
    ProductVariantForm,
    BulkVariantForm,
    AddAttributeValueForm,
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
from django.db.models.functions import TruncMonth, TruncDay, Coalesce, ExtractMonth
from django.core.paginator import Paginator
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
    SiteSettings,
    AttributeType,
    AttributeValue,
    ProductVariant,
    Shop,
    ShopStock,
    SalesTicket,
    SalesLine,
    StockMovement,
)
from .utils import run_allocation
import json
import calendar
from django.urls import reverse
from django.db import transaction
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_POST
from django.views.decorators.http import require_http_methods
import decimal
from django.template.loader import render_to_string
from django.core.mail import send_mail
from django.http import HttpResponse
import csv
import secrets


def _pos_receipt_number(prefix: str) -> str:
    """Unique POS receipt; constrained to Sales.receipt_number max_length=20."""
    t = timezone.now()
    return f"{prefix}{t.strftime('%Y%m%d%H%M%S')}{secrets.randbelow(1000):03d}"[:20]


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
        
        # Update inventory — only allow known safe fields
        ALLOWED_FIELDS = {
            'name', 'purchase_price', 'selling_price', 'quantity_in_Stock',
            'size', 'on_sale', 'category', 'description', 'reorder_point',
            'lead_time_days', 'markup_percent',
        }
        for key, value in data.items():
            if key in ALLOWED_FIELDS:
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

    # Calculate profit margin
    profit_margin = None
    if inventory.purchase_price and inventory.purchase_price > 0:
        profit_margin = ((inventory.selling_price - inventory.purchase_price) / inventory.purchase_price) * 100

    context = {
        'inventory': inventory,
        'total_sales': total_sales,
        'total_quantity_sold': total_quantity_sold,
        'total_returns': total_returns,
        'net_quantity': net_quantity,
        'profit_margin': profit_margin,
    }
    print(inventory.last_sale_date)

    return render(request,'inventory/per_product.html',context)

@login_required 
def add_product(request):
    # Get return_to and order_id from query params
    return_to = request.GET.get('return_to') or request.POST.get('return_to')
    order_id = request.GET.get('order_id') or request.POST.get('order_id')

    if request.method == 'POST':
        form = AddInventoryForm(request.POST, request.FILES)
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

            # Handle redirection based on return_to parameter
            if return_to == 'import_order' and order_id:
                return redirect('import_order_detail', pk=order_id)
            else:
                return redirect('inventory')
        else:
            # Add form errors to messages for debugging
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')
    else:
        form = AddInventoryForm()

    return render(request, 'inventory/inventory_add.html', {
        'form': form,
        'title': 'Add New Product',
        'return_to': return_to,
        'order_id': order_id,
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
    Supports variant_id for products with variants.
    """
    inventory = get_object_or_404(Inventory, pk=pk)

    try:
        with transaction.atomic():
            # Re-fetch with a row-level lock inside the transaction so concurrent sales
            # on the same product serialize here rather than racing on stock quantity.
            inventory = Inventory.objects.select_for_update().get(pk=pk)
            quantity_sold = int(request.POST.get('quantity_sold'))
            sale_price = Decimal(request.POST.get('sale_price'))
            discount = Decimal(request.POST.get('discount_applied', 0))
            payment_method = request.POST.get('payment_method', 'CASH').upper()
            customer_id = request.POST.get('customer_id')
            due_date_str = request.POST.get('due_date')
            deposit = Decimal(request.POST.get('deposit', '0') or '0')
            variant_id = request.POST.get('variant_id')

            # Handle variant sales
            variant = None
            if variant_id:
                try:
                    variant = ProductVariant.objects.get(pk=variant_id, product=inventory)
                except ProductVariant.DoesNotExist:
                    return JsonResponse({
                        'success': False,
                        'error': 'Variant not found'
                    })

            # Determine stock source (variant or parent product)
            if variant:
                available_stock = variant.quantity_in_stock
                stock_source = 'variant'
            else:
                available_stock = inventory.quantity_in_Stock
                stock_source = 'product'

            # Validation
            if quantity_sold <= 0:
                return JsonResponse({
                    'success': False,
                    'error': 'Quantity must be greater than 0'
                })

            if quantity_sold > available_stock:
                return JsonResponse({
                    'success': False,
                    'error': f'Not enough stock. Available: {available_stock}'
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

            # Enforce the user's personal max discount limit
            if hasattr(request.user, 'profile') and discount > request.user.profile.max_discount_percent:
                return JsonResponse({
                    'success': False,
                    'error': f'Discount exceeds your permitted maximum of {request.user.profile.max_discount_percent}%'
                })

            # Calculate total amount
            discounted_price = sale_price * (1 - discount / 100)
            total_amount = discounted_price * quantity_sold

            # Helper function to reduce stock (handles both variant and product)
            def reduce_stock(qty, reason):
                if variant:
                    variant.quantity_in_stock -= qty
                    variant.save(update_fields=['quantity_in_stock'])
                    # Also create stock movement for the parent product (for reporting)
                    StockMovement.objects.create(
                        inventory_item=inventory,
                        movement_type='OUT',
                        quantity=qty,
                        reason=f'{reason} (Variant: {variant.sku})'
                    )
                else:
                    inventory.quantity_in_Stock -= qty
                    inventory.save(update_fields=['quantity_in_Stock'])
                    StockMovement.objects.create(
                        inventory_item=inventory,
                        movement_type='OUT',
                        quantity=qty,
                        reason=reason
                    )

            if payment_method == 'CREDIT':
                print('[CREDIT] Start credit sale processing')
                # Validate customer and due date
                if not customer_id or not due_date_str:
                    print('[CREDIT][ERROR] Missing customer_id or due_date')
                    return JsonResponse({'success': False, 'error': 'customer_id and due_date are required for CREDIT sales'})
                
                from .models import Customer
                from accounting.models import ARInvoice
                
                try:
                    # select_for_update acquires a row-level lock so concurrent requests
                    # cannot both read the same balance and both pass the credit check.
                    customer = Customer.objects.select_for_update().get(pk=customer_id)
                    print(f"[CREDIT] Customer: {customer.id} - {customer.name}")
                except Customer.DoesNotExist:
                    print(f"[CREDIT][ERROR] Customer {customer_id} not found")
                    return JsonResponse({'success': False, 'error': 'Customer not found'})

                # Authorize within limit
                if customer.current_balance + total_amount > customer.credit_limit:
                    print(f"[CREDIT][ERROR] Credit limit exceeded: balance={customer.current_balance}, limit={customer.credit_limit}, sale={total_amount}")
                    return JsonResponse({'success': False, 'error': f'Credit limit exceeded. Available: ${customer.credit_limit - customer.current_balance}'})

                # Reduce stock and record movement
                print(f"[CREDIT] Reducing stock: qty={quantity_sold}")
                reduce_stock(quantity_sold, 'Credit sale (on account)')
                inventory.last_sale_date = timezone.now()
                inventory.save(update_fields=['last_sale_date'])
                print(f"[CREDIT] Stock reduced")

                # Create sales record (delivered)
                from .utils import get_setting
                receipt_prefix = get_setting('receipt_prefix', 'RCP')
                receipt_number = _pos_receipt_number(receipt_prefix)
                sale = Sales.objects.create(
                    inventory_item=inventory,
                    product_variant=variant,  # Link to variant if applicable
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
                print(f"[CREDIT] Sales record created: id={sale.id}, receipt={receipt_number}, variant={variant.sku if variant else 'N/A'}")

                # Create AR invoice then post accounting
                from datetime import datetime as dt
                due_date = dt.strptime(due_date_str, '%Y-%m-%d').date()
                inv_no = f"AR{timezone.now().strftime('%Y%m%d%H%M%S')}{secrets.randbelow(10000):04d}"
                ar = ARInvoice.objects.create(
                    customer=customer,
                    invoice_number=inv_no,
                    invoice_date=timezone.now().date(),
                    due_date=due_date,
                    total_amount=total_amount,
                    sale=sale
                )
                print(f"[CREDIT] AR Invoice created: {ar.invoice_number}")
                
                # Update customer balance
                customer.current_balance = (customer.current_balance or Decimal('0')) + total_amount
                customer.save(update_fields=['current_balance'])
                print(f"[CREDIT] Customer balance updated: {customer.current_balance}")

                from accounting.utils import post_credit_sale
                post_credit_sale(sale, ar)
                print(f"[CREDIT] GL entries posted successfully")

                print('[CREDIT] Completed successfully')
                return JsonResponse({
                    'success': True,
                    'message': f'Credit sale recorded. AR Invoice: {ar.invoice_number}',
                    'invoice_number': ar.invoice_number,
                    'total_amount': str(total_amount),
                    'remaining_stock': inventory.quantity_in_Stock
                })

            if payment_method == 'LAYBY':
                print('[LAYBY] Start layby processing')
                if not customer_id:
                    print('[LAYBY][ERROR] Missing customer_id')
                    return JsonResponse({'success': False, 'error': 'customer_id is required for LAYBY'})
                print('[LAYBY] Importing layby models from accounting')
                from .models import Customer
                from accounting.models import LaybyPlan, LaybyItem, LaybyPayment
                customer = get_object_or_404(Customer, pk=customer_id)
                print(f"[LAYBY] Customer: {customer.id} - {customer.name}")

                try:
                    # Reserve stock now
                    print(f"[LAYBY] Reserve stock: qty={quantity_sold}")
                    reduce_stock(quantity_sold, 'Layby reserve')
                    print(f"[LAYBY] Stock reserved")

                    plan = LaybyPlan.objects.create(
                        customer=customer,
                        deposit_amount=deposit,
                        total_price=total_amount,
                    )
                    print(f"[LAYBY] Plan created: id={plan.id}, total={total_amount}, deposit={deposit}")

                    # Record a non-fulfilled layby sale shell
                    item = LaybyItem.objects.create(
                        plan=plan,
                        inventory_item=inventory,
                        quantity=quantity_sold,
                        unit_price=discounted_price,
                    )
                    print(f"[LAYBY] Item created: id={item.id}, qty={quantity_sold}, unit={discounted_price}")

                    if deposit and deposit > 0:
                        print(f"[LAYBY] Creating deposit payment: amount={deposit}")
                        payment = LaybyPayment.objects.create(
                            plan=plan,
                            amount=deposit,
                            recorded_by=request.user,
                        )
                        print(f"[LAYBY] Deposit payment saved: id={payment.id}")

                    # Create a Sales row for visibility in sales table (payment_method LAYBY)
                    try:
                        from .models import Sales as SalesModel
                        layby_prefix = get_setting('layby_prefix', 'LB')
                        receipt_number = _pos_receipt_number(layby_prefix)
                        sale_row = SalesModel.objects.create(
                            inventory_item=inventory,
                            product_variant=variant,  # Link to variant if applicable
                            quantity_sold=quantity_sold,
                            sale_price=sale_price,
                            discount_applied=discount,
                            total_amount=total_amount,
                            receipt_number=receipt_number,
                            sale_date=timezone.now(),
                            recorded_by=request.user,
                            payment_method='LAYBY',
                            customer=customer
                        )
                        print(f"[LAYBY] Sales row created: id={sale_row.id}, receipt={receipt_number}, variant={variant.sku if variant else 'N/A'}")
                    except Exception as e:
                        print(f"[LAYBY][WARN] Failed to create Sales row for layby visibility: {e}")

                    print('[LAYBY] Completed successfully')
                    return JsonResponse({
                        'success': True,
                        'message': f'Layby plan created: #{plan.id}',
                        'layby_plan_id': plan.id,
                        'total_price': str(total_amount),
                        'deposit': str(deposit),
                        'remaining_stock': inventory.quantity_in_Stock
                    })
                except Exception as e:
                    print(f"[LAYBY][ERROR] Exception during layby processing: {e}")
                    return JsonResponse({'success': False, 'error': f'Layby failed: {e}'})

            # Default: CASH sale
            receipt_prefix = get_setting('receipt_prefix', 'RCP')
            receipt_number = _pos_receipt_number(receipt_prefix)

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
                product_variant=variant,  # Link to variant if applicable
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

            # Update stock using helper function
            reduce_stock(quantity_sold, f'Sale (Receipt: {receipt_number})')
            inventory.last_sale_date = timezone.now()
            inventory.save(update_fields=['last_sale_date'])

            from accounting.utils import post_cash_sale
            post_cash_sale(sale)

            # Get remaining stock (from variant or product)
            remaining_stock = variant.quantity_in_stock if variant else inventory.quantity_in_Stock

            return JsonResponse({
                'success': True,
                'message': f'Sale completed successfully! Receipt: {receipt_number}',
                'receipt_number': receipt_number,
                'total_amount': str(total_amount),
                'remaining_stock': remaining_stock
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

    # Totals by payment method — 3 filters on a pre-filtered queryset
    methods = ['CASH', 'CREDIT', 'LAYBY']
    totals_by_method = {
        m: qs.filter(payment_method=m).aggregate(total=Sum('total_amount'))['total'] or Decimal('0')
        for m in methods
    }

    # Single query: group by day + payment_method, then pivot in Python
    # Replaces the previous 96-query loop (31 days × 3 payment methods × 1 aggregate each)
    raw = (
        qs
        .annotate(day=TruncDay('sale_date'))
        .values('day', 'payment_method')
        .annotate(total=Sum('total_amount'))
        .order_by('day')
    )
    # Build a lookup: {date: {method: total}}
    pivot = {}
    for row in raw:
        d = row['day'].date()
        pivot.setdefault(d, {})
        pivot[d][row['payment_method']] = row['total'] or Decimal('0')

    daily_rows = []
    for i in range(30, -1, -1):
        day = (tz.now() - timedelta(days=i)).date()
        day_data = pivot.get(day, {})
        cash = day_data.get('CASH', Decimal('0'))
        credit = day_data.get('CREDIT', Decimal('0'))
        layby = day_data.get('LAYBY', Decimal('0'))
        daily_rows.append({
            'date': day,
            'cash': float(cash),
            'credit': float(credit),
            'layby': float(layby),
            'total': float(cash + credit + layby),
        })

    return render(request, 'inventory/sales_report_simple.html', {
        'totals_by_method': totals_by_method,
        'daily_rows': daily_rows,
    })

# ===== Simple endpoints to manage Customers, AR, Layby =====
@login_required
def ar_list(request):
    from accounting.models import ARInvoice
    from django.db.models import Case, When, BooleanField
    qs = ARInvoice.objects.select_related('customer').order_by('due_date')
    # Compute summary stats from the full queryset before paginating
    today = timezone.now().date()
    totals = qs.aggregate(
        total_outstanding=Sum('total_amount'),
        total_paid=Sum('amount_paid'),
    )
    total_outstanding = (totals['total_outstanding'] or 0) - (totals['total_paid'] or 0)
    overdue_count = qs.filter(due_date__lt=today, status__in=['PENDING', 'PARTIAL']).count()
    partial_count = qs.filter(status='PARTIAL').count()
    invoice_count = qs.count()
    paginator = Paginator(qs, 50)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'inventory/ar_list.html', {
        'invoices': page_obj,
        'page_obj': page_obj,
        'total_outstanding': total_outstanding,
        'overdue_count': overdue_count,
        'invoice_count': invoice_count,
        'partial_count': partial_count,
        'today': today.isoformat(),
    })

@login_required
def layby_list(request):
    from accounting.models import LaybyPlan
    plans = LaybyPlan.objects.select_related('customer').order_by('-created_date')
    # Compute stats from full queryset before paginating
    active_count = plans.filter(status='ACTIVE').count()
    fulfilled_count = plans.filter(status='FULFILLED').count()
    total_remaining = plans.filter(status='ACTIVE').aggregate(
        r=Sum('total_price'), p=Sum('amount_paid')
    )
    total_remaining_val = (total_remaining['r'] or 0) - (total_remaining['p'] or 0)
    today = timezone.now().date().isoformat()
    paginator = Paginator(plans, 50)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'inventory/layby_list.html', {
        'plans': page_obj,
        'page_obj': page_obj,
        'total_remaining': total_remaining_val,
        'active_count': active_count,
        'fulfilled_count': fulfilled_count,
        'today': today,
    })
@login_required
def customers_list(request):
    qs = Customer.objects.all().order_by('name')
    # Aggregate stats from full set before paginating
    active_count = qs.filter(status='ACTIVE').count()
    suspended_count = qs.filter(status='SUSPENDED').count()
    inactive_count = qs.filter(status='INACTIVE').count()
    total_balance = qs.aggregate(total=Sum('current_balance'))['total'] or 0
    paginator = Paginator(qs, 50)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'inventory/customers_list.html', {
        'customers': page_obj,
        'page_obj': page_obj,
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
    from accounting.models import LaybyPlan, JournalEntry, JournalLine
    from accounting.utils import require_gl

    plan = get_object_or_404(LaybyPlan, pk=pk)
    if plan.status != 'ACTIVE':
        messages.error(request, 'Plan not active')
        return redirect('dashboard')
    try:
        with transaction.atomic():
            unearned = require_gl('2300')
            sales_acct = require_gl('4000')
            cogs_acct = require_gl('5000')
            inventory_acct = require_gl('1300')

            je = JournalEntry.objects.create(memo=f'Layby fulfill plan#{plan.id}', created_by=request.user)
            recognize_amount = plan.amount_paid
            total_price = plan.total_price or Decimal('0')
            JournalLine.objects.create(entry=je, account=unearned, debit=recognize_amount, description='Recognize revenue')
            JournalLine.objects.create(entry=je, account=sales_acct, credit=recognize_amount, description='Sales revenue')
            total_cogs = Decimal('0')
            for item in plan.items.select_related('inventory_item'):
                cogs_amount = (item.inventory_item.purchase_price or Decimal('0')) * (item.quantity or 0)
                total_cogs += cogs_amount
            if total_price > 0 and recognize_amount < total_price:
                total_cogs = (total_cogs * recognize_amount / total_price).quantize(Decimal('0.01'))
            if total_cogs > 0:
                JournalLine.objects.create(entry=je, account=cogs_acct, debit=total_cogs, description='Cost of goods sold')
                JournalLine.objects.create(entry=je, account=inventory_acct, credit=total_cogs, description='Inventory reduction')
            je.assert_balanced()
            plan.status = 'FULFILLED'
            plan.save(update_fields=['status'])
    except Exception as exc:
        messages.error(request, str(exc))
        return redirect('dashboard')
    # Mark related layby sales as completed cash sales for reporting visibility
    try:
        from .models import Sales as SalesModel
        updated = 0
        for item in plan.items.select_related('inventory_item'):
            qs = SalesModel.objects.filter(
                inventory_item=item.inventory_item,
                customer=plan.customer,
                payment_method='LAYBY'
            )
            updated += qs.update(payment_method='CASH')
        if updated:
            print(f"[LAYBY] Fulfill plan#{plan.id}: updated {updated} sales rows to CASH")
    except Exception as e:
        print(f"[LAYBY][WARN] Could not update sales rows on fulfill: {e}")
    messages.success(request, 'Layby fulfilled')
    return redirect('dashboard')

@login_required
@require_POST
def layby_cancel(request, pk):
    from accounting.models import LaybyPlan, JournalEntry, JournalLine
    from accounting.utils import MissingGLAccountError, require_gl

    plan = get_object_or_404(LaybyPlan, pk=pk)
    fee = Decimal(request.POST.get('cancellation_fee', '0') or '0')
    try:
        with transaction.atomic():
            for item in plan.items.select_related('inventory_item'):
                inv = item.inventory_item
                inv.quantity_in_Stock += item.quantity
                inv.save(update_fields=['quantity_in_Stock'])
                StockMovement.objects.create(
                    inventory_item=inv, movement_type='IN', quantity=item.quantity,
                    reason=f'Layby cancel plan#{plan.id}',
                )
            refund = max(Decimal('0'), (plan.amount_paid or Decimal('0')) - fee)
            unpaid = (plan.total_price or Decimal('0')) - (plan.amount_paid or Decimal('0'))
            unearned = require_gl('2300')
            cash = require_gl('1000')
            ar = require_gl('1200')
            je = JournalEntry.objects.create(memo=f'Layby cancel plan#{plan.id}', created_by=request.user)
            if refund > 0:
                JournalLine.objects.create(entry=je, account=unearned, debit=refund, description='Refund customer')
                JournalLine.objects.create(entry=je, account=cash, credit=refund, description='Cash out')
            if fee > 0:
                other_income = require_gl('4800')
                JournalLine.objects.create(entry=je, account=unearned, debit=fee, description='Forfeit fee')
                JournalLine.objects.create(entry=je, account=other_income, credit=fee, description='Layby forfeit income')
            if unpaid > 0:
                JournalLine.objects.create(entry=je, account=unearned, debit=unpaid, description='Release unpaid commitment (clear AR)')
                JournalLine.objects.create(
                    entry=je, account=ar, credit=unpaid, description='Clear layby receivable', customer=plan.customer,
                )
            je.assert_balanced()
            if plan.customer:
                plan.customer.current_balance = (plan.customer.current_balance or Decimal('0')) - unpaid
                plan.customer.save(update_fields=['current_balance'])
            if plan.ar_invoice:
                plan.ar_invoice.status = 'CANCELLED'
                plan.ar_invoice.save(update_fields=['status', 'last_updated'])
            plan.status = 'CANCELLED'
            plan.save(update_fields=['status'])
    except MissingGLAccountError as exc:
        messages.error(request, str(exc))
        return redirect('dashboard')
    messages.success(request, 'Layby cancelled')
    return redirect('dashboard')


@login_required
@require_http_methods(["POST"])
def checkout_ticket(request):
    """Create a SalesTicket from a cart JSON payload and post to GL/cashbook.

    POST body (JSON):
    {
        "shop_id": 1,
        "terms": "IMMEDIATE" | "CREDIT" | "LAYBY",
        "tender_type": "CASH" | "ECOCASH" | "BANK_TRANSFER" | "CARD",
        "tender_reference": "ECA123",   // optional, for EcoCash/bank
        "customer_id": 5,               // required for CREDIT/LAYBY
        "due_date": "2026-05-15",       // required for CREDIT
        "initial_deposit": "50.00",     // optional for LAYBY
        "discount_percent": "10.0",
        "lines": [
            {"id": 3, "variant_id": null, "qty": 2, "unit_price": "115.00"},
            ...
        ]
    }
    """
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'success': False, 'error': 'Invalid JSON body'})

    try:
        with transaction.atomic():
            from accounting.utils import post_ticket
            from accounting.models import LaybyPayment

            shop_id = data.get('shop_id')
            if not shop_id:
                return JsonResponse({'success': False, 'error': 'shop_id is required'})
            shop = get_object_or_404(Shop, pk=shop_id, is_active=True)

            terms = (data.get('terms') or 'IMMEDIATE').upper()
            if terms not in ('IMMEDIATE', 'CREDIT', 'LAYBY'):
                return JsonResponse({'success': False, 'error': f'Invalid terms: {terms}'})

            tender_type = (data.get('tender_type') or 'CASH').upper()
            if tender_type not in ('CASH', 'ECOCASH', 'BANK_TRANSFER', 'CARD'):
                return JsonResponse({'success': False, 'error': f'Invalid tender_type: {tender_type}'})

            discount_percent = Decimal(str(data.get('discount_percent') or 0))
            if discount_percent < 0 or discount_percent > 100:
                return JsonResponse({'success': False, 'error': 'discount_percent must be 0-100'})
            if (hasattr(request.user, 'profile')
                    and discount_percent > request.user.profile.max_discount_percent):
                return JsonResponse({
                    'success': False,
                    'error': f'Discount exceeds your limit of {request.user.profile.max_discount_percent}%',
                })

            customer = None
            if terms in ('CREDIT', 'LAYBY'):
                cid = data.get('customer_id')
                if not cid:
                    return JsonResponse({'success': False, 'error': 'customer_id required for CREDIT/LAYBY'})
                customer = get_object_or_404(Customer, pk=cid)

            lines_data = data.get('lines') or []
            if not lines_data:
                return JsonResponse({'success': False, 'error': 'Cart is empty'})

            from .models import DailyCashUp
            if DailyCashUp.is_day_closed(shop, timezone.localdate()):
                return JsonResponse({
                    'success': False,
                    'error': f'Trading day is already closed for {shop.name}. Open a new day.',
                })

            vat_rate = SiteSettings.get_settings().tax_rate or Decimal('0')

            ticket = SalesTicket.objects.create(
                shop=shop,
                cashier=request.user,
                customer=customer,
                terms=terms,
                tender_type=tender_type,
                tender_reference=data.get('tender_reference') or '',
            )

            for ld in lines_data:
                inv_id = ld.get('id')
                variant_id = ld.get('variant_id')
                qty = int(ld.get('qty', 1))
                unit_price = Decimal(str(ld.get('unit_price', 0)))

                if qty <= 0:
                    return JsonResponse({'success': False, 'error': 'Line qty must be > 0'})
                if unit_price <= 0:
                    return JsonResponse({'success': False, 'error': 'Line unit_price must be > 0'})

                inv = get_object_or_404(Inventory, pk=inv_id)
                variant = None
                if variant_id:
                    variant = get_object_or_404(ProductVariant, pk=variant_id, product=inv)

                stock_row = ShopStock.get_or_create_for(shop, inv, variant)
                if stock_row.quantity < qty:
                    label = variant.sku if variant else inv.name
                    return JsonResponse({
                        'success': False,
                        'error': f'Insufficient stock for {label}: {stock_row.quantity} available',
                    })

                discount_amount = (unit_price * qty * discount_percent / 100).quantize(Decimal('0.01'))

                line = SalesLine(
                    ticket=ticket,
                    inventory_item=inv,
                    variant=variant,
                    quantity=qty,
                    unit_price_incl_vat=unit_price,
                    discount_amount=discount_amount,
                    unit_cost=inv.purchase_price or Decimal('0'),
                )
                line.compute(vat_rate=vat_rate)
                line.save()

            ticket.recalc_totals(save=True)
            post_ticket(ticket, user=request.user)

            if terms == 'LAYBY':
                initial_deposit = Decimal(str(data.get('initial_deposit') or 0))
                if initial_deposit > 0:
                    from accounting.models import LaybyPlan
                    plan = LaybyPlan.objects.filter(ticket=ticket).first()
                    if plan:
                        LaybyPayment.objects.create(
                            plan=plan,
                            amount=initial_deposit,
                            reference=ticket.receipt_number,
                            recorded_by=request.user,
                        )

            return JsonResponse({
                'success': True,
                'receipt_number': ticket.receipt_number,
                'total': str(ticket.total_incl_vat),
                'subtotal_excl': str(ticket.subtotal_excl_vat),
                'vat': str(ticket.vat_total),
                'items_count': ticket.lines.count(),
                'terms': terms,
                'tender_type': tender_type,
            })

    except ValueError as exc:
        return JsonResponse({'success': False, 'error': str(exc)})
    except Exception as exc:
        logger.exception('checkout_ticket failed')
        return JsonResponse({'success': False, 'error': f'Server error: {exc}'})


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
@require_POST
def sales_return(request, sale_id):
    sale = get_object_or_404(Sales, pk=sale_id)
    quantity_str = request.POST.get('quantity_returned')
    reason = request.POST.get('reason', '').strip()

    try:
        quantity = int(quantity_str or 0)
    except (TypeError, ValueError):
        messages.error(request, 'Invalid return quantity')
        return redirect('sales_summary')

    if quantity <= 0:
        messages.error(request, 'Return quantity must be greater than 0')
        return redirect('sales_summary')

    if quantity > sale.remaining_quantity:
        messages.error(request, f'Return quantity exceeds remaining quantity ({sale.remaining_quantity})')
        return redirect('sales_summary')

    try:
        with transaction.atomic():
            return_obj = Return.objects.create(
                inventory_item=sale.inventory_item,
                quantity_returned=quantity,
                reason=reason or 'Customer return',
                receipt_number=sale.receipt_number,
                sale=sale,
            )

            sale.quantity_returned += quantity
            sale.save(update_fields=['quantity_returned'])

            inventory_item = sale.inventory_item
            inventory_item.quantity_in_Stock += quantity
            inventory_item.save(update_fields=['quantity_in_Stock'])

            StockMovement.objects.create(
                inventory_item=inventory_item,
                movement_type='IN',
                quantity=quantity,
                reason=f'Return: {reason or "Customer return"} (Receipt: {sale.receipt_number or "N/A"})'
            )

            # Post GL reversal entries
            try:
                from accounting.utils import post_sales_return
                post_sales_return(return_obj, user=request.user)
            except Exception as e:
                print(f"[RETURN] Warning: GL posting failed for return {return_obj.id}: {e}")

            messages.success(request, f'Returned {quantity} of {inventory_item.name} successfully')
    except Exception as e:
        messages.error(request, f'Error processing return: {e}')

    return redirect('sales_summary')

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

            with transaction.atomic():
                # Lock the inventory row to prevent concurrent over-subtraction
                obsolete_inventory = Inventory.objects.select_for_update().get(pk=obsolete_inventory.pk)

                if quantity_damaged > obsolete_inventory.quantity_in_Stock:
                    messages.error(request, f"Cannot mark {quantity_damaged} units as damaged — only {obsolete_inventory.quantity_in_Stock} in stock.")
                    return redirect('damagedInventory', pk=obsolete_inventory.pk)

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

                # Post GL entry: Dr COGS/Loss, Cr Inventory
                try:
                    from accounting.utils import post_inventory_adjustment
                    post_inventory_adjustment(
                        obsolete_inventory,
                        quantity_damaged,
                        damage_description or 'Damaged goods',
                        adjustment_type='DAMAGE',
                        user=request.user
                    )
                except Exception as e:
                    logger.error('[DAMAGE] GL posting failed for %s: %s', obsolete_inventory.name, e, exc_info=True)

                # Create stock movement record
                StockMovement.objects.create(
                    inventory_item=obsolete_inventory,
                    movement_type='OUT',
                    quantity=quantity_damaged,
                    reason=f'Damaged: {damage_description or "Damaged goods"}'
                )

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

@login_required
def search(request):
    query = request.GET.get('q', '')
    if query:
        results = Inventory.objects.filter(name__icontains=query)
    else:
        results = Inventory.objects.none()
    return render(request, 'inventory/search_results.html', {
        'results': results,
        'query': query,
        'count': results.count()
    })

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
    from .utils import get_setting
    low_stock_threshold = get_setting('low_stock_threshold', 10)
    metrics = {
        'total_products': Inventory.objects.count(),
        'total_sales': float(Sales.objects.aggregate(total=Sum('total_amount'))['total'] or 0),
        'low_stock': Inventory.objects.filter(quantity_in_Stock__lte=low_stock_threshold).count(),
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


# ==================== STOCK CONTROL REPORTS ====================
@login_required
def low_stock_report(request):
    """Low stock and reorder recommendations report.
    Calculates recent sales velocity and suggests reorder quantity.
    """
    from django.utils import timezone as tz
    from datetime import timedelta
    days = max(1, min(int(request.GET.get('days', 30)), 365))
    cutoff = tz.now() - timedelta(days=days)

    # Single query: annotate each inventory item with its recent sales and returns
    # Replaces the previous 2-queries-per-item loop (O(N) → O(1) database round-trips)
    items = (
        Inventory.objects
        .select_related('category')
        .annotate(
            recent_sold=Coalesce(
                Sum('sales_records__quantity_sold', filter=Q(sales_records__sale_date__gte=cutoff)),
                0,
            ),
            recent_returned=Coalesce(
                Sum('sales_records__quantity_returned', filter=Q(sales_records__sale_date__gte=cutoff)),
                0,
            ),
        )
    )

    report_rows = []
    for item in items:
        net_sold = max(0, item.recent_sold - item.recent_returned)
        velocity = float(net_sold) / float(days) if days > 0 else 0.0
        days_of_stock = (float(item.quantity_in_Stock) / velocity) if velocity > 0 else None
        recommended = max(
            int(round(velocity * (item.lead_time_days or 0))) + (item.reorder_point or 0) - (item.quantity_in_Stock or 0),
            0
        )
        is_low = (item.quantity_in_Stock or 0) <= (item.reorder_point or 0)
        report_rows.append({
            'item': item,
            'stock': item.quantity_in_Stock,
            'reorder_point': item.reorder_point,
            'lead_time_days': item.lead_time_days,
            'velocity_per_day': round(velocity, 3),
            'days_of_stock': round(days_of_stock, 1) if days_of_stock is not None else None,
            'recommended_reorder': recommended,
            'is_low': is_low,
        })

    # Sort with low stock first
    report_rows.sort(key=lambda r: (not r['is_low'], -(r['recommended_reorder']), -(r['velocity_per_day'])))

    return render(request, 'inventory/low_stock_report.html', {
        'rows': report_rows,
        'days': days,
    })


@login_required
def inventory_valuation_report(request):
    """Inventory valuation by category and supplier with aging buckets."""
    from django.utils import timezone as tz
    from datetime import timedelta
    now = tz.now()

    items = Inventory.objects.select_related('category').all()

    def age_days(it):
        ref = it.last_sale_date or it.created_date
        return (now - ref).days if ref else 0

    buckets = {
        '0_30': {'label': '0-30', 'items': [], 'value': 0},
        '31_90': {'label': '31-90', 'items': [], 'value': 0},
        '91_180': {'label': '91-180', 'items': [], 'value': 0},
        '180_plus': {'label': '181+', 'items': [], 'value': 0},
    }

    by_category = {}
    by_supplier = {}

    total_value = 0
    potential_value = 0

    for it in items:
        stock = it.quantity_in_Stock or 0
        value = float((it.purchase_price or 0) * stock)
        potential = float((it.selling_price or 0) * stock)
        total_value += value
        potential_value += potential

        # Buckets
        d = age_days(it)
        key = '0_30' if d <= 30 else '31_90' if d <= 90 else '91_180' if d <= 180 else '180_plus'
        buckets[key]['items'].append(it)
        buckets[key]['value'] += value

        # Category
        cat = it.category.name if it.category else 'Uncategorized'
        if cat not in by_category:
            by_category[cat] = {'value': 0, 'potential': 0, 'count': 0}
        by_category[cat]['value'] += value
        by_category[cat]['potential'] += potential
        by_category[cat]['count'] += 1

        # Supplier (string field)
        sup = it.bought_from or 'Unknown'
        if sup not in by_supplier:
            by_supplier[sup] = {'value': 0, 'potential': 0, 'count': 0}
        by_supplier[sup]['value'] += value
        by_supplier[sup]['potential'] += potential
        by_supplier[sup]['count'] += 1

    margin_value = potential_value - total_value

    # Prepare sorted views
    cat_rows = sorted(({'name': k, **v} for k, v in by_category.items()), key=lambda r: -r['value'])
    sup_rows = sorted(({'name': k, **v} for k, v in by_supplier.items()), key=lambda r: -r['value'])

    return render(request, 'inventory/inventory_valuation.html', {
        'total_value': total_value,
        'potential_value': potential_value,
        'margin_value': margin_value,
        'buckets': buckets,
        'by_category': cat_rows,
        'by_supplier': sup_rows,
    })


@login_required
def inventory_valuation_export_csv(request):
    """Export detailed inventory valuation to CSV."""
    import csv
    from django.http import HttpResponse
    items = Inventory.objects.select_related('category').all().order_by('name')
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="inventory_valuation.csv"'
    writer = csv.writer(response)
    writer.writerow(['Product', 'Category', 'Supplier', 'Stock', 'Cost', 'Sell Price', 'Stock Value', 'Potential Value', 'Last Sale'])
    for it in items:
        stock = it.quantity_in_Stock or 0
        value = (it.purchase_price or 0) * stock
        potential = (it.selling_price or 0) * stock
        writer.writerow([
            it.name,
            it.category.name if it.category else '',
            it.bought_from or '',
            stock,
            f"{it.purchase_price}",
            f"{it.selling_price}",
            f"{value}",
            f"{potential}",
            it.last_sale_date.strftime('%Y-%m-%d') if it.last_sale_date else ''
        ])
    return response

@login_required
@require_POST
def delete_inventory_category(request, pk):
    category = get_object_or_404(Inventory_category, pk=pk)
    category.delete()
    return redirect('inventory_category')

@login_required
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
            default_markup = request.POST.get('default_markup')
            
            if not name:
                return JsonResponse({
                    'success': False,
                    'error': 'Category name is required'
                })
                
            category = Inventory_category.objects.create(
                name=name,
                description=description,
                default_markup=default_markup
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

            # Convert numeric fields - handle empty strings properly
            # Purchase price (allows null, default 0)
            purchase_price_val = data.get('purchase_price', '').strip() if data.get('purchase_price') else ''
            if purchase_price_val:
                data['purchase_price'] = Decimal(purchase_price_val)
            else:
                data['purchase_price'] = Decimal('0')
            
            # Selling price (allows null, default 0)
            selling_price_val = data.get('selling_price', '').strip() if data.get('selling_price') else ''
            if selling_price_val:
                data['selling_price'] = Decimal(selling_price_val)
            else:
                data['selling_price'] = Decimal('0')
            
            # Quantity in stock
            quantity_val = data.get('quantity_in_Stock', '').strip() if data.get('quantity_in_Stock') else ''
            if quantity_val:
                data['quantity_in_Stock'] = int(quantity_val)
            else:
                data['quantity_in_Stock'] = 0
            
            # Size is a CharField, not IntegerField - keep as string or convert to empty string
            if 'size' in data:
                size_val = data.get('size', '') or ''
                if size_val and isinstance(size_val, str):
                    size_val = size_val.strip()
                    data['size'] = size_val if size_val else None
                elif not size_val:
                    data['size'] = None  # Allow null for size
            
            # Optional new fields
            if 'reorder_point' in data:
                reorder_val = data.get('reorder_point', '') or ''
                if reorder_val and str(reorder_val).strip():
                    data['reorder_point'] = int(reorder_val)
                else:
                    data['reorder_point'] = 0
            if 'lead_time_days' in data:
                lead_time_val = data.get('lead_time_days', '') or ''
                if lead_time_val and str(lead_time_val).strip():
                    data['lead_time_days'] = int(lead_time_val)
                else:
                    data['lead_time_days'] = 0
            
            # Handle weight if present (optional DecimalField)
            if 'weight' in data:
                weight_val = data.get('weight', '') or ''
                if weight_val and str(weight_val).strip():
                    data['weight'] = Decimal(str(weight_val).strip())
                else:
                    data['weight'] = None  # Allow null for weight

            # Validate prices only if both are non-zero
            if data['selling_price'] > 0 and data['purchase_price'] > 0 and data['selling_price'] < data['purchase_price']:
                messages.error(request, "Selling price cannot be less than purchase price")
                return redirect('inventory_update', pk=pk)

            # Update inventory — only allow known safe fields
            ALLOWED_FIELDS = {
                'name', 'purchase_price', 'selling_price', 'quantity_in_Stock',
                'size', 'on_sale', 'description', 'reorder_point',
                'lead_time_days', 'markup_percent', 'weight',
            }
            for key, value in data.items():
                if key in ALLOWED_FIELDS:
                    setattr(inventory, key, value)

            # Handle image upload
            if 'image' in request.FILES:
                inventory.image = request.FILES['image']
                # Thumbnail will be auto-generated by the model signal

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
    
    # Only show extra empty form if there are no existing items
    # This prevents showing 2 forms (1 existing + 1 extra) when there's already an item
    from inventory.forms import ImportOrderItemForm
    from django.forms import inlineformset_factory
    
    existing_items_count = import_order.items.count()
    # min_num=1 ensures at least 1 form is shown, so we don't need extra=1
    DynamicItemFormSet = inlineformset_factory(
        ImportOrder,
        ImportOrderItem,
        form=ImportOrderItemForm,
        extra=0,  # min_num already ensures we have at least 1 form
        min_num=1,
        validate_min=True,
        can_delete=True
    )
    items_formset = DynamicItemFormSet(instance=import_order)
    expenses_formset = ImportExpenseFormSet(instance=import_order)

    if request.method == 'POST':
        if 'save_items' in request.POST:
            # Use the same dynamic formset for POST requests
            items_formset = DynamicItemFormSet(request.POST, instance=import_order)
            if items_formset.is_valid():
                items_formset.save()
                messages.success(request, 'Order items saved successfully')
                return redirect('import_order_detail', pk=pk)
            else:
                # Collect detailed error messages
                error_messages = []
                for i, form in enumerate(items_formset):
                    if form.errors:
                        for field, errors in form.errors.items():
                            if field != '__all__':
                                field_label = field
                                if field in form.fields:
                                    field_label = form.fields[field].label if hasattr(form.fields[field], 'label') else field
                                for error in errors:
                                    error_messages.append(f"Item {i+1}: {field_label} - {error}")
                
                # Add formset-level errors
                if items_formset.non_form_errors():
                    for error in items_formset.non_form_errors():
                        error_messages.append(str(error))
                
                if error_messages:
                    error_text = 'Please fix the following errors:<br>• ' + '<br>• '.join(error_messages[:5])
                    if len(error_messages) > 5:
                        error_text += f'<br>... and {len(error_messages) - 5} more error(s)'
                    messages.error(request, error_text)
                else:
                    messages.error(request, 'Please fix errors in the items form')
        elif 'save_expenses' in request.POST:
            expenses_formset = ImportExpenseFormSet(request.POST, instance=import_order)
            if expenses_formset.is_valid():
                expenses_formset.save()
                messages.success(request, 'Order expenses saved successfully')
                return redirect('import_order_detail', pk=pk)
            else:
                # Collect detailed error messages
                error_messages = []
                for i, form in enumerate(expenses_formset):
                    if form.errors:
                        for field, errors in form.errors.items():
                            if field != '__all__':
                                field_label = field
                                if field in form.fields:
                                    field_label = form.fields[field].label if hasattr(form.fields[field], 'label') else field
                                for error in errors:
                                    error_messages.append(f"Expense {i+1}: {field_label} - {error}")
                
                # Add formset-level errors
                if expenses_formset.non_form_errors():
                    for error in expenses_formset.non_form_errors():
                        error_messages.append(str(error))
                
                if error_messages:
                    error_text = 'Please fix the following errors:<br>• ' + '<br>• '.join(error_messages[:5])
                    if len(error_messages) > 5:
                        error_text += f'<br>... and {len(error_messages) - 5} more error(s)'
                    messages.error(request, error_text)
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
@require_POST
def import_order_cancel(request, pk):
    """Cancel an import order (soft delete)"""
    import_order = get_object_or_404(ImportOrder, pk=pk)

    # Safety checks
    if import_order.status in ['RECEIVED', 'COMPLETED']:
        messages.error(request, 'Cannot cancel an order that has already been received. Goods have been added to stock.')
        return redirect('import_order_detail', pk=pk)

    if import_order.status == 'CANCELLED':
        messages.warning(request, 'This order is already cancelled.')
        return redirect('import_order_detail', pk=pk)

    # Check if there are paid supplier invoices
    paid_invoices = import_order.invoices.filter(amount_paid__gt=0)
    if paid_invoices.exists():
        messages.error(request, 'Cannot cancel order with paid invoices. Please contact accounting to reverse payments first.')
        return redirect('import_order_detail', pk=pk)

    try:
        # Mark as cancelled
        import_order.status = 'CANCELLED'
        import_order.save()

        messages.success(request, f'Import Order {import_order.order_number} has been cancelled. All data is preserved for records.')
        messages.info(request, 'Items and expenses are locked. Unpaid invoices remain for accounting purposes.')

        return redirect('import_order_detail', pk=pk)

    except Exception as e:
        messages.error(request, f'Error cancelling order: {str(e)}')
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
def simple_pos(request):
    from .models import UserProfile
    if not hasattr(request.user, 'profile'):
        UserProfile.objects.create(
            user=request.user,
            role='admin' if request.user.is_staff else 'sales',
            can_make_sales=True,
            can_manage_inventory=request.user.is_staff,
        )

    if not request.user.profile.can_access_pos:
        messages.error(request, 'You do not have permission to access the Point of Sale system.')
        return redirect('dashboard')

    # Resolve current shop: query param > user default > first active shop
    shops = Shop.objects.filter(is_active=True).order_by('name')
    current_shop = None
    shop_id_param = request.GET.get('shop_id') or request.POST.get('shop_id')
    if shop_id_param:
        current_shop = shops.filter(pk=shop_id_param).first()
    if not current_shop and hasattr(request.user.profile, 'default_shop') and request.user.profile.default_shop:
        current_shop = request.user.profile.default_shop if request.user.profile.default_shop.is_active else None
    if not current_shop:
        current_shop = shops.first()

    settings = SiteSettings.get_settings()
    customers = Customer.objects.filter(status='ACTIVE').order_by('name')

    context = {
        'user_role': request.user.profile.role,
        'max_discount': request.user.profile.max_discount_percent,
        'customers': customers,
        'shops': shops,
        'current_shop': current_shop,
        'vat_rate': settings.tax_rate if settings else 15,
        'currency_symbol': settings.currency_symbol if settings else '$',
    }

    return render(request, 'inventory/simple_pos.html', context)


# ──────────────────────────────────────────────────────────────────────────────
# D1 — Daily Z-report / cash-up
# ──────────────────────────────────────────────────────────────────────────────

@login_required
def cashup_preview(request, shop_pk):
    """Show today's running totals for a shop (before close-of-day).

    Also accepts ?date=YYYY-MM-DD to view a historical closed Z-report.
    """
    from .models import DailyCashUp
    shop = get_object_or_404(Shop, pk=shop_pk, is_active=True)

    date_str = request.GET.get('date')
    if date_str:
        try:
            from datetime import date as date_cls
            report_date = date_cls.fromisoformat(date_str)
        except ValueError:
            report_date = timezone.localdate()
    else:
        report_date = timezone.localdate()

    from datetime import timedelta as _td
    closed_record = DailyCashUp.objects.filter(shop=shop, date=report_date).first()
    summary = _build_day_summary(shop, report_date)

    immediate_total = sum([
        summary['cash_total'],
        summary['ecocash_total'],
        summary['bank_transfer_total'],
        summary['card_total'],
    ])
    tender_rows = [
        ('Cash', summary['cash_total'], 'fas fa-money-bill', 'bg-green-500'),
        ('EcoCash', summary['ecocash_total'], 'fas fa-mobile-alt', 'bg-blue-500'),
        ('Bank Transfer', summary['bank_transfer_total'], 'fas fa-university', 'bg-indigo-500'),
        ('Card', summary['card_total'], 'fas fa-credit-card', 'bg-purple-500'),
    ]

    context = {
        'shop': shop,
        'report_date': report_date,
        'prev_date': report_date - _td(days=1),
        'next_date': report_date + _td(days=1),
        'summary': summary,
        'closed_record': closed_record,
        'shops': Shop.objects.filter(is_active=True).order_by('name'),
        'tender_rows': tender_rows,
        'immediate_total': immediate_total,
    }
    return render(request, 'inventory/daily_cashup.html', context)


@login_required
@require_http_methods(["POST"])
def cashup_close(request, shop_pk):
    """Close the trading day for a shop. Returns JSON."""
    from .models import DailyCashUp
    from django.utils.dateparse import parse_date

    if request.user.profile.role not in ('admin', 'manager'):
        return JsonResponse({'success': False, 'error': 'Only managers can close the day'})

    shop = get_object_or_404(Shop, pk=shop_pk, is_active=True)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        body = {}

    date_str = body.get('date') or timezone.localdate().isoformat()
    try:
        from datetime import date as date_cls
        report_date = date_cls.fromisoformat(date_str)
    except ValueError:
        return JsonResponse({'success': False, 'error': 'Invalid date'})

    if DailyCashUp.is_day_closed(shop, report_date):
        return JsonResponse({'success': False, 'error': f'{report_date} is already closed for {shop.name}'})

    summary = _build_day_summary(shop, report_date)
    counted_cash_raw = body.get('counted_cash')
    counted_cash = Decimal(str(counted_cash_raw)) if counted_cash_raw not in (None, '') else None
    cash_variance = (counted_cash - summary['cash_total']) if counted_cash is not None else None

    with transaction.atomic():
        record = DailyCashUp.objects.create(
            shop=shop,
            date=report_date,
            z_number=DailyCashUp.next_z_number(shop),
            ticket_count=summary['ticket_count'],
            gross_sales=summary['gross_sales'],
            discount_total=summary['discount_total'],
            vat_total=summary['vat_total'],
            net_sales=summary['net_sales'],
            cash_total=summary['cash_total'],
            ecocash_total=summary['ecocash_total'],
            bank_transfer_total=summary['bank_transfer_total'],
            card_total=summary['card_total'],
            counted_cash=counted_cash,
            cash_variance=cash_variance,
            cashier_summary=summary['cashier_summary'],
            notes=body.get('notes', ''),
            closed_by=request.user,
        )

    return JsonResponse({
        'success': True,
        'z_number': record.z_number,
        'z_label': str(record),
        'redirect_url': f'/inventory/cashup/{shop_pk}/?date={report_date}',
    })


def _build_day_summary(shop, report_date):
    """Aggregate SalesTickets for shop+date into a summary dict."""
    tickets = (
        SalesTicket.objects
        .filter(shop=shop, created_at__date=report_date, voided=False)
        .select_related('cashier')
    )

    from django.db.models import Sum as _Sum

    agg = tickets.aggregate(
        gross=_Sum('total_incl_vat'),
        vat=_Sum('vat_total'),
        discount=_Sum('discount_total'),
    )
    gross_sales = agg['gross'] or Decimal('0')
    vat_total = agg['vat'] or Decimal('0')
    discount_total = agg['discount'] or Decimal('0')
    net_sales = gross_sales - discount_total

    # Tender breakdown — only IMMEDIATE tickets move cash on day of sale
    immediate = tickets.filter(terms='IMMEDIATE')
    tender_agg = {}
    for tender in ('CASH', 'ECOCASH', 'BANK_TRANSFER', 'CARD'):
        tender_agg[tender] = (
            immediate.filter(tender_type=tender)
            .aggregate(t=_Sum('total_incl_vat'))['t'] or Decimal('0')
        )

    # Cashier breakdown
    from collections import defaultdict
    cashier_map = defaultdict(lambda: {'ticket_count': 0, 'total': Decimal('0')})
    for t in tickets:
        key = t.cashier_id or 0
        label = (t.cashier.get_full_name() or t.cashier.username) if t.cashier else 'Unknown'
        cashier_map[key]['name'] = label
        cashier_map[key]['cashier_id'] = key
        cashier_map[key]['ticket_count'] += 1
        cashier_map[key]['total'] += t.total_incl_vat or Decimal('0')

    cashier_summary = [
        {
            'cashier_id': v['cashier_id'],
            'name': v['name'],
            'ticket_count': v['ticket_count'],
            'total': str(v['total']),
        }
        for v in cashier_map.values()
    ]

    return {
        'ticket_count': tickets.count(),
        'gross_sales': gross_sales,
        'vat_total': vat_total,
        'discount_total': discount_total,
        'net_sales': net_sales,
        'cash_total': tender_agg['CASH'],
        'ecocash_total': tender_agg['ECOCASH'],
        'bank_transfer_total': tender_agg['BANK_TRANSFER'],
        'card_total': tender_agg['CARD'],
        'cashier_summary': cashier_summary,
        'tickets': tickets,
    }


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
    """AJAX endpoint for fast product search by common fields.

    Accepts optional ?shop_id=<pk> to return per-shop stock from ShopStock
    instead of the global Inventory.quantity_in_Stock field.
    """
    query = request.GET.get('q', '').strip()
    if not query:
        return JsonResponse({'products': []})

    shop = None
    shop_id = request.GET.get('shop_id')
    if shop_id:
        try:
            shop = Shop.objects.get(pk=shop_id, is_active=True)
        except Shop.DoesNotExist:
            pass

    products = (
        Inventory.objects.filter(
            Q(product_code__icontains=query)
            | Q(name__icontains=query)
            | Q(label__icontains=query)
            | Q(size__icontains=query)
            | Q(category__name__icontains=query)
            | Q(variants__sku__icontains=query)
        )
        .select_related('category')
        .prefetch_related('variants__attribute_values__attribute_type')
        .distinct()
        .order_by('product_code')[:10]
    )

    results = []
    for product in products:
        thumbnail_url = product.thumbnail.url if product.thumbnail else None

        if shop:
            # Per-shop stock from ShopStock join table
            shop_stock_row = ShopStock.get_or_create_for(shop, product, None)
            qty_in_stock = int(shop_stock_row.quantity)
        else:
            qty_in_stock = product.quantity_in_Stock if not product.has_variants else product.total_stock

        product_data = {
            'id': product.id,
            'product_code': product.product_code,
            'name': product.name,
            'label': product.label,
            'selling_price': str(product.selling_price),
            'quantity_in_stock': qty_in_stock,
            'total_stock': qty_in_stock,
            'category': product.category.name if product.category else 'Uncategorized',
            'display_name': f"{product.product_code} - {product.name}",
            'thumbnail_url': thumbnail_url,
            'has_variants': product.has_variants,
        }

        if product.has_variants:
            variants_data = []
            for variant in product.variants.filter(is_active=True):
                if shop:
                    v_stock_row = ShopStock.get_or_create_for(shop, product, variant)
                    v_qty = int(v_stock_row.quantity)
                else:
                    v_qty = variant.quantity_in_stock

                reorder = getattr(ShopStock.objects.filter(
                    shop=shop, inventory_item=product, variant=variant
                ).first(), 'reorder_point', 5) if shop else 5

                attrs = []
                for attr_val in variant.attribute_values.all():
                    attrs.append({
                        'type': attr_val.attribute_type.display_name,
                        'value': attr_val.display_value or attr_val.value,
                        'color_code': attr_val.color_code,
                    })
                variants_data.append({
                    'id': variant.id,
                    'sku': variant.sku,
                    'attributes': attrs,
                    'attribute_string': variant.attribute_string,
                    'selling_price': str(variant.effective_selling_price),
                    'quantity_in_stock': v_qty,
                    'is_low_stock': v_qty <= reorder,
                })
            product_data['variants'] = variants_data
            product_data['variant_count'] = len(variants_data)

        results.append(product_data)

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


# ==================== ADVANCED STOCK REPORTS ====================

@login_required
def stock_movement_report(request):
    """Comprehensive stock movement report with filters for date, product, type, and user."""
    form = DateRangeForm(request.GET or None)
    movements = StockMovement.objects.select_related('inventory_item').all().order_by('-stock_date')

    # Apply filters
    if form.is_valid():
        start_date = form.cleaned_data.get('start_date')
        end_date = form.cleaned_data.get('end_date')
        if start_date:
            movements = movements.filter(stock_date__date__gte=start_date)
        if end_date:
            movements = movements.filter(stock_date__date__lte=end_date)

    # Product filter
    product_id = request.GET.get('product')
    if product_id:
        movements = movements.filter(inventory_item_id=product_id)

    # Movement type filter
    movement_type = request.GET.get('movement_type')
    if movement_type:
        movements = movements.filter(movement_type=movement_type)

    # Calculate running balance for each product
    movements_with_balance = []
    for movement in movements[:500]:  # Limit to 500 for performance
        movements_with_balance.append(movement)

    # Get summary statistics
    total_in = movements.filter(movement_type='IN').aggregate(total=Sum('quantity'))['total'] or 0
    total_out = movements.filter(movement_type='OUT').aggregate(total=Sum('quantity'))['total'] or 0

    # Calculate specific movement types
    total_sales = movements.filter(movement_type='OUT', reason__icontains='sale').aggregate(total=Sum('quantity'))['total'] or 0
    total_returns = movements.filter(movement_type='IN', reason__icontains='return').aggregate(total=Sum('quantity'))['total'] or 0
    total_damages = movements.filter(movement_type='OUT').filter(
        Q(reason__icontains='damage') | Q(reason__icontains='obsolete')
    ).aggregate(total=Sum('quantity'))['total'] or 0

    # Get distinct products for filter dropdown
    products = Inventory.objects.all().order_by('name')

    context = {
        'form': form,
        'movements': movements_with_balance,
        'total_in': total_in,
        'total_out': total_out,
        'net_movement': total_in - total_out,
        'total_sales': total_sales,
        'total_returns': total_returns,
        'total_damages': total_damages,
        'products': products,
        'selected_product': product_id or '',
        'selected_type': movement_type or '',
    }
    return render(request, 'inventory/stock_movement_report.html', context)


@login_required
def stock_movement_export_csv(request):
    """Export stock movements to CSV with same filters as report."""
    form = DateRangeForm(request.GET or None)
    movements = StockMovement.objects.select_related('inventory_item').all().order_by('-stock_date')

    # Apply same filters as main report
    if form.is_valid():
        start_date = form.cleaned_data.get('start_date')
        end_date = form.cleaned_data.get('end_date')
        if start_date:
            movements = movements.filter(stock_date__date__gte=start_date)
        if end_date:
            movements = movements.filter(stock_date__date__lte=end_date)

    product_id = request.GET.get('product')
    if product_id:
        movements = movements.filter(inventory_item_id=product_id)

    movement_type = request.GET.get('movement_type')
    if movement_type:
        movements = movements.filter(movement_type=movement_type)

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="stock_movements.csv"'

    writer = csv.writer(response)
    writer.writerow(['Date', 'Product Code', 'Product Name', 'Type', 'Quantity', 'Reason', 'Current Stock'])

    for m in movements:
        writer.writerow([
            m.stock_date.strftime('%Y-%m-%d %H:%M'),
            m.inventory_item.product_code,
            m.inventory_item.name,
            m.get_movement_type_display(),
            m.quantity,
            m.reason or '',
            m.inventory_item.quantity_in_Stock
        ])

    return response


@login_required
def dead_stock_report(request):
    """Report on slow-moving and dead stock items with no sales in X days."""
    days_threshold = max(1, min(int(request.GET.get('days', 90)), 730))
    category_id = request.GET.get('category')
    min_value = Decimal(request.GET.get('min_value', '0') or '0')

    cutoff_date = timezone.now() - timedelta(days=days_threshold)

    # Get all items with their last sale date
    items = Inventory.objects.select_related('category').all()

    # Filter by category if specified
    if category_id:
        items = items.filter(category_id=category_id)

    dead_stock_items = []
    for item in items:
        # Calculate days since last sale
        last_sale = item.last_sale_date
        if last_sale:
            days_since_sale = (timezone.now() - last_sale).days
        else:
            days_since_sale = (timezone.now() - item.created_date).days if item.created_date else 999

        # Only include items with no recent sales
        if days_since_sale >= days_threshold:
            stock_value = (item.purchase_price or Decimal('0')) * (item.quantity_in_Stock or 0)

            # Apply minimum value filter
            if stock_value >= min_value:
                dead_stock_items.append({
                    'item': item,
                    'days_since_sale': days_since_sale,
                    'stock': item.quantity_in_Stock,
                    'stock_value': stock_value,
                    'potential_loss': stock_value,
                    'last_sale_date': last_sale or item.created_date,
                })

    # Sort by value (highest first)
    dead_stock_items.sort(key=lambda x: -x['stock_value'])

    # Calculate totals
    total_items = len(dead_stock_items)
    total_value = sum(item['stock_value'] for item in dead_stock_items)
    total_units = sum(item['stock'] for item in dead_stock_items)

    # Get categories for filter
    categories = Inventory_category.objects.all().order_by('name')

    context = {
        'items': dead_stock_items,
        'days_threshold': days_threshold,
        'total_items': total_items,
        'total_value': total_value,
        'total_units': total_units,
        'categories': categories,
        'selected_category': category_id or '',
        'min_value': min_value,
    }
    return render(request, 'inventory/dead_stock_report.html', context)


@login_required
def inventory_turnover_report(request):
    """Calculate inventory turnover ratio for products and categories."""
    form = DateRangeForm(request.GET or None)

    # Default to last 90 days
    end_date = timezone.now()
    start_date = end_date - timedelta(days=90)

    if form.is_valid():
        if form.cleaned_data.get('start_date'):
            start_date = timezone.make_aware(datetime.combine(form.cleaned_data['start_date'], datetime.min.time()))
        if form.cleaned_data.get('end_date'):
            end_date = timezone.make_aware(datetime.combine(form.cleaned_data['end_date'], datetime.max.time()))

    # Category filter
    category_id = request.GET.get('category')

    items = Inventory.objects.select_related('category').all()
    if category_id:
        items = items.filter(category_id=category_id)

    turnover_data = []
    for item in items:
        # Get COGS for period (purchase_price * quantity_sold)
        sales_qs = Sales.objects.filter(
            inventory_item=item,
            sale_date__range=(start_date, end_date)
        )

        total_qty_sold = sales_qs.aggregate(total=Sum('quantity_sold'))['total'] or 0
        cogs = (item.purchase_price or Decimal('0')) * total_qty_sold

        # Average inventory = (beginning + ending) / 2
        # Simplified: use current stock as proxy
        avg_inventory_value = (item.purchase_price or Decimal('0')) * (item.quantity_in_Stock or 0)

        # Turnover ratio = COGS / Average Inventory
        if avg_inventory_value > 0:
            turnover_ratio = float(cogs) / float(avg_inventory_value)
        else:
            turnover_ratio = 0.0 if cogs == 0 else float('inf')

        # Classification
        if turnover_ratio >= 4:
            classification = 'Excellent'
        elif turnover_ratio >= 2:
            classification = 'Good'
        elif turnover_ratio >= 1:
            classification = 'Fair'
        else:
            classification = 'Poor'

        if total_qty_sold > 0 or avg_inventory_value > 0:  # Only show items with activity
            turnover_data.append({
                'item': item,
                'cogs': cogs,
                'avg_inventory_value': avg_inventory_value,
                'turnover_ratio': round(turnover_ratio, 2) if turnover_ratio != float('inf') else 'N/A',
                'classification': classification,
                'qty_sold': total_qty_sold,
            })

    # Sort by turnover ratio (descending)
    turnover_data.sort(key=lambda x: x['turnover_ratio'] if isinstance(x['turnover_ratio'], (int, float)) else 0, reverse=True)

    # Calculate category averages
    category_summary = {}
    for data in turnover_data:
        cat_name = data['item'].category.name if data['item'].category else 'Uncategorized'
        if cat_name not in category_summary:
            category_summary[cat_name] = {'count': 0, 'total_ratio': 0}
        if isinstance(data['turnover_ratio'], (int, float)):
            category_summary[cat_name]['count'] += 1
            category_summary[cat_name]['total_ratio'] += data['turnover_ratio']

    for cat in category_summary:
        if category_summary[cat]['count'] > 0:
            category_summary[cat]['avg_ratio'] = round(
                category_summary[cat]['total_ratio'] / category_summary[cat]['count'], 2
            )

    categories = Inventory_category.objects.all().order_by('name')

    context = {
        'form': form,
        'turnover_data': turnover_data,
        'category_summary': category_summary,
        'categories': categories,
        'selected_category': category_id or '',
        'start_date': start_date,
        'end_date': end_date,
    }
    return render(request, 'inventory/inventory_turnover_report.html', context)


@login_required
def stock_forecast_report(request):
    """Predict stockout dates based on sales velocity."""
    forecast_days = max(1, min(int(request.GET.get('days', 60)), 365))

    # Calculate velocity over last 30 days
    velocity_window = 30
    cutoff = timezone.now() - timedelta(days=velocity_window)

    items = Inventory.objects.select_related('category').all()

    forecast_data = []
    for item in items:
        # Calculate daily velocity
        recent_sales = Sales.objects.filter(
            inventory_item=item,
            sale_date__gte=cutoff
        ).aggregate(
            total_qty=Sum('quantity_sold'),
            total_returns=Sum('quantity_returned')
        )

        qty_sold = (recent_sales['total_qty'] or 0) - (recent_sales['total_returns'] or 0)
        daily_velocity = float(qty_sold) / float(velocity_window) if velocity_window > 0 else 0.0

        current_stock = item.quantity_in_Stock or 0

        # Calculate days until stockout
        if daily_velocity > 0:
            days_until_stockout = int(current_stock / daily_velocity)
        else:
            days_until_stockout = 999  # No recent sales

        # Calculate recommended order date (consider lead time)
        reorder_lead_time = item.lead_time_days or 0
        recommended_order_days = max(0, days_until_stockout - reorder_lead_time)

        # Projected stockout date
        if days_until_stockout < 999:
            stockout_date = timezone.now() + timedelta(days=days_until_stockout)
            recommended_order_date = timezone.now() + timedelta(days=recommended_order_days)
        else:
            stockout_date = None
            recommended_order_date = None

        # Urgency level
        if days_until_stockout <= 7:
            urgency = 'critical'
        elif days_until_stockout <= 14:
            urgency = 'high'
        elif days_until_stockout <= 30:
            urgency = 'medium'
        else:
            urgency = 'low'

        # Only include items that will run out within forecast period
        if days_until_stockout <= forecast_days:
            forecast_data.append({
                'item': item,
                'current_stock': current_stock,
                'daily_velocity': round(daily_velocity, 2),
                'days_until_stockout': days_until_stockout,
                'stockout_date': stockout_date,
                'recommended_order_date': recommended_order_date,
                'urgency': urgency,
                'lead_time_days': reorder_lead_time,
            })

    # Sort by urgency (soonest first)
    forecast_data.sort(key=lambda x: x['days_until_stockout'])

    # Summary stats
    critical_count = sum(1 for f in forecast_data if f['urgency'] == 'critical')
    high_count = sum(1 for f in forecast_data if f['urgency'] == 'high')

    context = {
        'forecast_data': forecast_data,
        'forecast_days': forecast_days,
        'critical_count': critical_count,
        'high_count': high_count,
        'total_items': len(forecast_data),
    }
    return render(request, 'inventory/stock_forecast_report.html', context)


# ==================== SITE SETTINGS ====================

@login_required
def site_settings(request):
    """View and edit site-wide settings. Admin only."""
    # Check if user has admin privileges
    if not (request.user.is_superuser or
            (hasattr(request.user, 'profile') and request.user.profile.is_admin)):
        messages.error(request, "You don't have permission to access settings.")
        return redirect('dashboard')

    # Get or create settings (singleton)
    settings = SiteSettings.get_settings()

    if request.method == 'POST':
        form = SiteSettingsForm(request.POST, request.FILES, instance=settings)
        if form.is_valid():
            settings = form.save(commit=False)
            settings.updated_by = request.user
            settings.save()
            messages.success(request, "Settings saved successfully!")
            return redirect('site_settings')
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = SiteSettingsForm(instance=settings)

    # Get sections for template tabs
    sections = form.get_fields_by_section()

    # Get setup status for System Setup tab
    from accounting.models import GLAccount
    setup_status = {
        'gl_accounts_count': GLAccount.objects.count(),
        'attributes_count': AttributeType.objects.count(),
        'last_setup_log': request.session.pop('setup_log', None),
    }

    context = {
        'form': form,
        'sections': sections,
        'settings': settings,
        'active_tab': request.GET.get('tab', 'company'),
        'setup_status': setup_status,
    }
    return render(request, 'inventory/site_settings.html', context)


@login_required
def settings_reset_defaults(request):
    """Reset settings to default values. Admin only."""
    if not (request.user.is_superuser or
            (hasattr(request.user, 'profile') and request.user.profile.is_admin)):
        messages.error(request, "You don't have permission to reset settings.")
        return redirect('dashboard')

    if request.method == 'POST':
        # Delete existing settings and create fresh defaults
        SiteSettings.objects.filter(pk=1).delete()
        SiteSettings.get_settings()  # Creates new with defaults
        messages.success(request, "Settings have been reset to defaults.")
        return redirect('site_settings')

    return redirect('site_settings')


# ==================== SYSTEM SETUP VIEWS ====================

@login_required
def setup_init_gl_accounts(request):
    """Initialize GL accounts via web interface. Admin only."""
    if not (request.user.is_superuser or
            (hasattr(request.user, 'profile') and request.user.profile.is_admin)):
        messages.error(request, "You don't have permission to run setup tasks.")
        return redirect('site_settings')

    if request.method == 'POST':
        from accounting.models import GLAccount

        accounts = [
            # Assets
            {'code': '1000', 'name': 'Cash', 'type': 'ASSET'},
            {'code': '1200', 'name': 'Accounts Receivable', 'type': 'ASSET'},
            {'code': '1300', 'name': 'Inventory', 'type': 'ASSET'},
            {'code': '1400', 'name': 'Prepaid Expenses', 'type': 'ASSET'},
            {'code': '1500', 'name': 'Fixed Assets', 'type': 'ASSET'},

            # Liabilities
            {'code': '2000', 'name': 'Accounts Payable', 'type': 'LIAB'},
            {'code': '2100', 'name': 'Short-term Debt', 'type': 'LIAB'},
            {'code': '2300', 'name': 'Unearned Revenue', 'type': 'LIAB'},

            # Equity
            {'code': '3000', 'name': "Owner's Equity", 'type': 'EQUITY'},
            {'code': '3100', 'name': 'Retained Earnings', 'type': 'EQUITY'},
            {'code': '3900', 'name': 'Opening Balance Equity', 'type': 'EQUITY'},

            # Income
            {'code': '4000', 'name': 'Sales Revenue', 'type': 'INCOME'},
            {'code': '4100', 'name': 'Sales Discounts', 'type': 'CONTRA_REV'},
            {'code': '4800', 'name': 'Other Income', 'type': 'INCOME'},

            # Expenses
            {'code': '5000', 'name': 'Cost of Goods Sold (COGS)', 'type': 'EXP'},
            {'code': '6000', 'name': 'Rent Expense', 'type': 'EXP'},
            {'code': '6100', 'name': 'Utilities Expense', 'type': 'EXP'},
            {'code': '6200', 'name': 'Wages Expense', 'type': 'EXP'},
            {'code': '6300', 'name': 'Freight Expense', 'type': 'EXP'},
            {'code': '6400', 'name': 'Marketing Expense', 'type': 'EXP'},
            {'code': '6900', 'name': 'Other Expenses', 'type': 'EXP'},
        ]

        created_count = 0
        updated_count = 0
        log_lines = []

        for acc_data in accounts:
            account, created = GLAccount.objects.get_or_create(
                code=acc_data['code'],
                defaults={
                    'name': acc_data['name'],
                    'type': acc_data['type'],
                    'is_active': True
                }
            )

            if created:
                log_lines.append(f"[+] Created: {acc_data['code']} - {acc_data['name']}")
                created_count += 1
            else:
                # Update name/type if different
                if account.name != acc_data['name'] or account.type != acc_data['type']:
                    account.name = acc_data['name']
                    account.type = acc_data['type']
                    account.save()
                    log_lines.append(f"[~] Updated: {acc_data['code']} - {acc_data['name']}")
                    updated_count += 1
                else:
                    log_lines.append(f"[*] Exists:  {acc_data['code']} - {acc_data['name']}")

        log_lines.append(f"\nSummary: {created_count} created, {updated_count} updated")
        request.session['setup_log'] = '\n'.join(log_lines)

        messages.success(request, f"GL Accounts: {created_count} created, {updated_count} updated")
        from django.urls import reverse
        return redirect(reverse('site_settings') + '?tab=setup')

    from django.urls import reverse
    return redirect(reverse('site_settings') + '?tab=setup')


@login_required
def setup_seed_attributes(request):
    """Seed product attributes via web interface. Admin only."""
    if not (request.user.is_superuser or
            (hasattr(request.user, 'profile') and request.user.profile.is_admin)):
        messages.error(request, "You don't have permission to run setup tasks.")
        return redirect('site_settings')

    if request.method == 'POST':
        log_lines = []
        created_types = 0
        created_values = 0

        # Size attribute type
        size_type, created = AttributeType.objects.get_or_create(
            name='Size',
            defaults={'display_name': 'Size', 'display_order': 1, 'is_active': True}
        )
        if created:
            log_lines.append("[+] Created attribute type: Size")
            created_types += 1

        # Clothing sizes
        clothing_sizes = [
            ('XS', 'XS', 1), ('S', 'S', 2), ('M', 'M', 3), ('L', 'L', 4),
            ('XL', 'XL', 5), ('XXL', 'XXL', 6), ('XXXL', '3XL', 7),
        ]
        for value, display, order in clothing_sizes:
            obj, created = AttributeValue.objects.get_or_create(
                attribute_type=size_type, value=value,
                defaults={'display_value': display, 'display_order': order, 'is_active': True}
            )
            if created:
                created_values += 1

        # Shoe sizes
        for size in range(36, 47):
            obj, created = AttributeValue.objects.get_or_create(
                attribute_type=size_type, value=str(size),
                defaults={'display_value': str(size), 'display_order': size, 'is_active': True}
            )
            if created:
                created_values += 1

        # Color attribute type
        color_type, created = AttributeType.objects.get_or_create(
            name='Color',
            defaults={'display_name': 'Color', 'display_order': 2, 'is_active': True}
        )
        if created:
            log_lines.append("[+] Created attribute type: Color")
            created_types += 1

        colors = [
            ('Black', '#000000'), ('White', '#FFFFFF'), ('Grey', '#808080'),
            ('Navy', '#000080'), ('Red', '#FF0000'), ('Blue', '#0000FF'),
            ('Green', '#008000'), ('Yellow', '#FFFF00'), ('Pink', '#FFC0CB'),
            ('Purple', '#800080'), ('Brown', '#8B4513'), ('Beige', '#F5F5DC'),
        ]
        for i, (color, code) in enumerate(colors, 1):
            obj, created = AttributeValue.objects.get_or_create(
                attribute_type=color_type, value=color,
                defaults={'display_value': color, 'color_code': code, 'display_order': i, 'is_active': True}
            )
            if created:
                created_values += 1

        # Material attribute type
        material_type, created = AttributeType.objects.get_or_create(
            name='Material',
            defaults={'display_name': 'Material', 'display_order': 3, 'is_active': True}
        )
        if created:
            log_lines.append("[+] Created attribute type: Material")
            created_types += 1

        materials = ['Cotton', 'Polyester', 'Wool', 'Silk', 'Linen', 'Denim', 'Leather']
        for i, mat in enumerate(materials, 1):
            obj, created = AttributeValue.objects.get_or_create(
                attribute_type=material_type, value=mat,
                defaults={'display_value': mat, 'display_order': i, 'is_active': True}
            )
            if created:
                created_values += 1

        log_lines.append(f"\nSummary: {created_types} types, {created_values} values created")
        log_lines.append(f"Total: {AttributeType.objects.count()} types, {AttributeValue.objects.count()} values")
        request.session['setup_log'] = '\n'.join(log_lines)

        messages.success(request, f"Product Attributes: {created_types} types, {created_values} values created")
        from django.urls import reverse
        return redirect(reverse('site_settings') + '?tab=setup')

    from django.urls import reverse
    return redirect(reverse('site_settings') + '?tab=setup')


@login_required
def setup_backfill_inventory(request):
    """Backfill inventory opening balance to GL. Admin only."""
    if not (request.user.is_superuser or
            (hasattr(request.user, 'profile') and request.user.profile.is_admin)):
        messages.error(request, "You don't have permission to run setup tasks.")
        return redirect('site_settings')

    if request.method == 'POST':
        from accounting.models import GLAccount, JournalEntry, JournalLine
        from django.db import transaction
        from django.db.models import Sum, F

        log_lines = []

        # Calculate current inventory value
        inventory_value = Inventory.objects.aggregate(
            total=Sum(F('quantity_in_Stock') * F('purchase_price'))
        )['total'] or Decimal('0')

        log_lines.append(f"Physical inventory value: ${inventory_value:,.2f}")

        if inventory_value <= 0:
            log_lines.append("No inventory value found. Nothing to backfill.")
            request.session['setup_log'] = '\n'.join(log_lines)
            messages.warning(request, "No inventory value found. Nothing to backfill.")
            from django.urls import reverse
            return redirect(reverse('site_settings') + '?tab=setup')

        try:
            inventory_account = GLAccount.objects.get(code='1300')
            current_gl_balance = inventory_account.balance
            log_lines.append(f"Current GL 1300 balance: ${current_gl_balance:,.2f}")
        except GLAccount.DoesNotExist:
            messages.error(request, "GL Account 1300 (Inventory) not found. Initialize GL accounts first.")
            from django.urls import reverse
            return redirect(reverse('site_settings') + '?tab=setup')

        adjustment = inventory_value - current_gl_balance
        log_lines.append(f"Adjustment needed: ${adjustment:,.2f}")

        if adjustment <= 0:
            log_lines.append("No adjustment needed - GL balance matches or exceeds inventory.")
            request.session['setup_log'] = '\n'.join(log_lines)
            messages.info(request, "No adjustment needed. GL balance already matches inventory.")
            from django.urls import reverse
            return redirect(reverse('site_settings') + '?tab=setup')

        # Get or create Opening Balance Equity account
        equity_account, created = GLAccount.objects.get_or_create(
            code='3900',
            defaults={'name': 'Opening Balance Equity', 'type': 'EQUITY', 'is_active': True}
        )
        if created:
            log_lines.append("[+] Created account 3900 - Opening Balance Equity")

        with transaction.atomic():
            je = JournalEntry.objects.create(
                memo='Opening balance - inventory on hand',
                reference='OPENING-INV',
                created_by=request.user
            )
            JournalLine.objects.create(
                entry=je, account=inventory_account,
                debit=adjustment, description='Opening inventory balance'
            )
            JournalLine.objects.create(
                entry=je, account=equity_account,
                credit=adjustment, description='Opening inventory balance'
            )

        log_lines.append(f"\n[+] Created journal entry #{je.id}")
        log_lines.append(f"Dr Inventory 1300: ${adjustment:,.2f}")
        log_lines.append(f"Cr Opening Balance Equity 3900: ${adjustment:,.2f}")
        request.session['setup_log'] = '\n'.join(log_lines)

        messages.success(request, f"Inventory opening balance posted: ${adjustment:,.2f}")
        from django.urls import reverse
        return redirect(reverse('site_settings') + '?tab=setup')

    from django.urls import reverse
    return redirect(reverse('site_settings') + '?tab=setup')


@login_required
def setup_run_all(request):
    """Run all setup tasks in sequence. Admin only."""
    if not (request.user.is_superuser or
            (hasattr(request.user, 'profile') and request.user.profile.is_admin)):
        messages.error(request, "You don't have permission to run setup tasks.")
        return redirect('site_settings')

    if request.method == 'POST':
        from accounting.models import GLAccount, JournalEntry, JournalLine
        from django.db import transaction
        from django.db.models import Sum, F

        log_lines = ["=== Running All Setup Tasks ===\n"]
        total_created = 0

        # 1. GL Accounts
        log_lines.append("--- GL Accounts ---")
        accounts = [
            {'code': '1000', 'name': 'Cash', 'type': 'ASSET'},
            {'code': '1200', 'name': 'Accounts Receivable', 'type': 'ASSET'},
            {'code': '1300', 'name': 'Inventory', 'type': 'ASSET'},
            {'code': '1400', 'name': 'Prepaid Expenses', 'type': 'ASSET'},
            {'code': '1500', 'name': 'Fixed Assets', 'type': 'ASSET'},
            {'code': '2000', 'name': 'Accounts Payable', 'type': 'LIAB'},
            {'code': '2100', 'name': 'Short-term Debt', 'type': 'LIAB'},
            {'code': '2300', 'name': 'Unearned Revenue', 'type': 'LIAB'},
            {'code': '3000', 'name': "Owner's Equity", 'type': 'EQUITY'},
            {'code': '3100', 'name': 'Retained Earnings', 'type': 'EQUITY'},
            {'code': '3900', 'name': 'Opening Balance Equity', 'type': 'EQUITY'},
            {'code': '4000', 'name': 'Sales Revenue', 'type': 'INCOME'},
            {'code': '4100', 'name': 'Sales Discounts', 'type': 'CONTRA_REV'},
            {'code': '4800', 'name': 'Other Income', 'type': 'INCOME'},
            {'code': '5000', 'name': 'Cost of Goods Sold (COGS)', 'type': 'EXP'},
            {'code': '6000', 'name': 'Rent Expense', 'type': 'EXP'},
            {'code': '6100', 'name': 'Utilities Expense', 'type': 'EXP'},
            {'code': '6200', 'name': 'Wages Expense', 'type': 'EXP'},
            {'code': '6300', 'name': 'Freight Expense', 'type': 'EXP'},
            {'code': '6400', 'name': 'Marketing Expense', 'type': 'EXP'},
            {'code': '6900', 'name': 'Other Expenses', 'type': 'EXP'},
        ]
        gl_created = 0
        for acc_data in accounts:
            account, created = GLAccount.objects.get_or_create(
                code=acc_data['code'],
                defaults={'name': acc_data['name'], 'type': acc_data['type'], 'is_active': True}
            )
            if created:
                gl_created += 1
        log_lines.append(f"GL Accounts: {gl_created} created, {GLAccount.objects.count()} total")
        total_created += gl_created

        # 2. Product Attributes
        log_lines.append("\n--- Product Attributes ---")
        attr_created = 0

        size_type, created = AttributeType.objects.get_or_create(
            name='Size', defaults={'display_name': 'Size', 'display_order': 1, 'is_active': True}
        )
        if created:
            attr_created += 1

        color_type, created = AttributeType.objects.get_or_create(
            name='Color', defaults={'display_name': 'Color', 'display_order': 2, 'is_active': True}
        )
        if created:
            attr_created += 1

        material_type, created = AttributeType.objects.get_or_create(
            name='Material', defaults={'display_name': 'Material', 'display_order': 3, 'is_active': True}
        )
        if created:
            attr_created += 1

        # Add basic values
        values_created = 0
        for val in ['XS', 'S', 'M', 'L', 'XL', 'XXL']:
            _, created = AttributeValue.objects.get_or_create(
                attribute_type=size_type, value=val,
                defaults={'display_value': val, 'display_order': 1, 'is_active': True}
            )
            if created:
                values_created += 1

        for val, code in [('Black', '#000'), ('White', '#FFF'), ('Grey', '#888'), ('Navy', '#008'), ('Red', '#F00')]:
            _, created = AttributeValue.objects.get_or_create(
                attribute_type=color_type, value=val,
                defaults={'display_value': val, 'color_code': code, 'display_order': 1, 'is_active': True}
            )
            if created:
                values_created += 1

        log_lines.append(f"Attributes: {attr_created} types, {values_created} values created")
        total_created += attr_created + values_created

        log_lines.append(f"\n=== Setup Complete: {total_created} items created ===")
        request.session['setup_log'] = '\n'.join(log_lines)

        messages.success(request, f"All setup tasks completed! {total_created} items created.")
        from django.urls import reverse
        return redirect(reverse('site_settings') + '?tab=setup')

    from django.urls import reverse
    return redirect(reverse('site_settings') + '?tab=setup')


# ==================== PRODUCT VARIANT VIEWS ====================

@login_required
def add_product_with_variants(request):
    """
    Step 1: Create a new product that will have variants.
    Collects basic product info and selects which attribute types to use.
    """
    if request.method == 'POST':
        form = ProductWithVariantsForm(request.POST, request.FILES)
        if form.is_valid():
            # Save product but don't create variants yet
            product = form.save()

            # Store selected attribute types in session for next step
            attr_type_ids = [at.id for at in form.cleaned_data['variant_attribute_types']]
            request.session['variant_product_id'] = product.id
            request.session['variant_attr_types'] = attr_type_ids

            messages.success(request, f'Product "{product.name}" created. Now select variant options.')
            return redirect('select_variant_attributes', pk=product.id)
    else:
        form = ProductWithVariantsForm()

    context = {
        'form': form,
        'title': 'Add Product with Variants',
        'step': 1,
        'total_steps': 3,
    }
    return render(request, 'inventory/add_product_with_variants.html', context)


@login_required
def select_variant_attributes(request, pk):
    """
    Step 2: Select which attribute values to create variants for.
    E.g., Select sizes S, M, L and colors Black, White
    """
    product = get_object_or_404(Inventory, pk=pk)

    if not product.has_variants:
        messages.error(request, "This product doesn't have variants enabled.")
        return redirect('per_product', pk=pk)

    # Get the attribute types for this product
    attribute_types = product.variant_attributes.filter(is_active=True)

    if request.method == 'POST':
        form = VariantAttributeSelectionForm(request.POST, attribute_types=attribute_types)
        if form.is_valid():
            # Store selected values in session
            selected_values = form.get_selected_values()
            request.session['variant_selected_values'] = {
                str(k): [v.id for v in vals] for k, vals in selected_values.items()
            }

            return redirect('configure_variants', pk=product.id)
    else:
        form = VariantAttributeSelectionForm(attribute_types=attribute_types)

    context = {
        'form': form,
        'product': product,
        'attribute_types': attribute_types,
        'title': f'Select Variant Options for {product.name}',
        'step': 2,
        'total_steps': 3,
    }
    return render(request, 'inventory/select_variant_attributes.html', context)


@login_required
def configure_variants(request, pk):
    """
    Step 3: Configure individual variant details (SKU, price, stock).
    Auto-generates all combinations of selected attributes.
    """
    from itertools import product as itertools_product

    product_obj = get_object_or_404(Inventory, pk=pk)

    if not product_obj.has_variants:
        messages.error(request, "This product doesn't have variants enabled.")
        return redirect('per_product', pk=pk)

    # Get selected values from session
    selected_values_raw = request.session.get('variant_selected_values', {})

    # Convert to AttributeValue objects
    attribute_types = product_obj.variant_attributes.filter(is_active=True).order_by('display_order')
    selected_values = {}
    for attr_type in attribute_types:
        val_ids = selected_values_raw.get(str(attr_type.id), [])
        if val_ids:
            selected_values[attr_type] = list(AttributeValue.objects.filter(id__in=val_ids))

    # Generate all combinations
    if selected_values:
        attr_types_list = list(selected_values.keys())
        values_lists = [selected_values[at] for at in attr_types_list]
        combinations = list(itertools_product(*values_lists))
    else:
        combinations = []

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'bulk_update':
            # Handle bulk updates
            bulk_form = BulkVariantForm(request.POST)
            if bulk_form.is_valid():
                # Apply bulk values to all variants
                pass  # Will be processed in main save

        if action == 'save_variants':
            # Save all variants
            created_count = 0
            with transaction.atomic():
                for i, combo in enumerate(combinations):
                    # Get form data for this variant
                    prefix = f'variant_{i}'
                    is_active = request.POST.get(f'{prefix}_is_active') == 'on'
                    sku = request.POST.get(f'{prefix}_sku', '').strip()
                    purchase_price = request.POST.get(f'{prefix}_purchase_price', '').strip()
                    selling_price = request.POST.get(f'{prefix}_selling_price', '').strip()
                    quantity = request.POST.get(f'{prefix}_quantity', '0').strip()
                    reorder_point = request.POST.get(f'{prefix}_reorder_point', '0').strip()

                    if not is_active:
                        continue  # Skip unchecked variants

                    # Generate SKU if not provided
                    if not sku:
                        base_code = product_obj.product_code or 'PROD'
                        abbrevs = [attr.value[:3].upper() for attr in combo]
                        sku = f"{base_code}-{'-'.join(abbrevs)}"

                    # Ensure unique SKU
                    if ProductVariant.objects.filter(sku=sku).exists():
                        # Append number to make unique
                        counter = 1
                        base_sku = sku
                        while ProductVariant.objects.filter(sku=sku).exists():
                            sku = f"{base_sku}-{counter}"
                            counter += 1

                    # Create variant
                    variant = ProductVariant.objects.create(
                        product=product_obj,
                        sku=sku,
                        purchase_price=decimal.Decimal(purchase_price) if purchase_price else None,
                        selling_price=decimal.Decimal(selling_price) if selling_price else None,
                        quantity_in_stock=int(quantity) if quantity else 0,
                        reorder_point=int(reorder_point) if reorder_point else 0,
                        is_active=True,
                    )

                    # Add attribute values
                    variant.attribute_values.set(combo)
                    created_count += 1

                    # Create stock movement if stock was added
                    if variant.quantity_in_stock > 0:
                        StockMovement.objects.create(
                            inventory_item=product_obj,
                            movement_type='IN',
                            quantity=variant.quantity_in_stock,
                            reason=f'Initial stock for variant {variant.sku}'
                        )

            # Clear session
            if 'variant_selected_values' in request.session:
                del request.session['variant_selected_values']
            if 'variant_product_id' in request.session:
                del request.session['variant_product_id']
            if 'variant_attr_types' in request.session:
                del request.session['variant_attr_types']

            messages.success(request, f'Created {created_count} variants for "{product_obj.name}"')
            return redirect('per_product', pk=product_obj.id)

    # Prepare variant data for template
    variant_data = []
    for i, combo in enumerate(combinations):
        attrs_display = " / ".join([attr.label for attr in combo])
        base_code = product_obj.product_code or 'PROD'
        abbrevs = [attr.value[:3].upper() for attr in combo]
        suggested_sku = f"{base_code}-{'-'.join(abbrevs)}"

        variant_data.append({
            'index': i,
            'attributes': combo,
            'attrs_display': attrs_display,
            'suggested_sku': suggested_sku,
            'default_purchase_price': product_obj.purchase_price,
            'default_selling_price': product_obj.selling_price,
            'default_reorder_point': product_obj.reorder_point,
        })

    bulk_form = BulkVariantForm()

    context = {
        'product': product_obj,
        'variant_data': variant_data,
        'bulk_form': bulk_form,
        'title': f'Configure Variants for {product_obj.name}',
        'step': 3,
        'total_steps': 3,
    }
    return render(request, 'inventory/configure_variants.html', context)


@login_required
def product_variants_list(request, pk):
    """View and manage existing variants for a product."""
    product = get_object_or_404(Inventory, pk=pk)

    if not product.has_variants:
        messages.error(request, "This product doesn't have variants enabled.")
        return redirect('per_product', pk=pk)

    variants = product.variants.all().prefetch_related('attribute_values')

    context = {
        'product': product,
        'variants': variants,
    }
    return render(request, 'inventory/product_variants_list.html', context)


@login_required
def edit_variant(request, pk):
    """Edit a single variant's details."""
    variant = get_object_or_404(ProductVariant, pk=pk)

    if request.method == 'POST':
        form = ProductVariantForm(request.POST, instance=variant)
        if form.is_valid():
            form.save()
            messages.success(request, f'Variant "{variant.sku}" updated successfully.')
            return redirect('product_variants_list', pk=variant.product.id)
    else:
        form = ProductVariantForm(instance=variant)

    context = {
        'form': form,
        'variant': variant,
        'product': variant.product,
    }
    return render(request, 'inventory/edit_variant.html', context)


@login_required
@require_POST
def delete_variant(request, pk):
    """Delete a variant."""
    variant = get_object_or_404(ProductVariant, pk=pk)
    product_id = variant.product.id
    sku = variant.sku

    variant.delete()
    messages.success(request, f'Variant "{sku}" deleted.')

    return redirect('product_variants_list', pk=product_id)


@login_required
def add_variant_to_product(request, pk):
    """Add a new variant to an existing product with variants."""
    from itertools import product as itertools_product

    product = get_object_or_404(Inventory, pk=pk)

    if not product.has_variants:
        messages.error(request, "This product doesn't have variants enabled.")
        return redirect('per_product', pk=pk)

    attribute_types = product.variant_attributes.filter(is_active=True).order_by('display_order')

    if request.method == 'POST':
        # Collect selected attribute values
        selected_values = []
        for attr_type in attribute_types:
            value_id = request.POST.get(f'attr_{attr_type.id}')
            if value_id:
                try:
                    attr_value = AttributeValue.objects.get(id=value_id)
                    selected_values.append(attr_value)
                except AttributeValue.DoesNotExist:
                    pass

        if len(selected_values) == attribute_types.count():
            # Check if variant already exists
            existing = product.get_variant_by_attributes(selected_values)
            if existing:
                messages.error(request, f'A variant with these attributes already exists: {existing.sku}')
            else:
                # Create variant
                sku = request.POST.get('sku', '').strip()
                if not sku:
                    base_code = product.product_code or 'PROD'
                    abbrevs = [attr.value[:3].upper() for attr in selected_values]
                    sku = f"{base_code}-{'-'.join(abbrevs)}"

                # Ensure unique SKU
                if ProductVariant.objects.filter(sku=sku).exists():
                    counter = 1
                    base_sku = sku
                    while ProductVariant.objects.filter(sku=sku).exists():
                        sku = f"{base_sku}-{counter}"
                        counter += 1

                purchase_price = request.POST.get('purchase_price', '').strip()
                selling_price = request.POST.get('selling_price', '').strip()
                quantity = request.POST.get('quantity_in_stock', '0').strip()
                reorder_point = request.POST.get('reorder_point', '0').strip()

                variant = ProductVariant.objects.create(
                    product=product,
                    sku=sku,
                    purchase_price=decimal.Decimal(purchase_price) if purchase_price else None,
                    selling_price=decimal.Decimal(selling_price) if selling_price else None,
                    quantity_in_stock=int(quantity) if quantity else 0,
                    reorder_point=int(reorder_point) if reorder_point else 0,
                    is_active=True,
                )
                variant.attribute_values.set(selected_values)

                if variant.quantity_in_stock > 0:
                    StockMovement.objects.create(
                        inventory_item=product,
                        movement_type='IN',
                        quantity=variant.quantity_in_stock,
                        reason=f'Initial stock for variant {variant.sku}'
                    )

                messages.success(request, f'Variant "{sku}" created successfully.')
                return redirect('product_variants_list', pk=product.id)
        else:
            messages.error(request, 'Please select all attribute values.')

    # Get available values for each attribute type
    attribute_data = []
    for attr_type in attribute_types:
        values = AttributeValue.objects.filter(
            attribute_type=attr_type,
            is_active=True
        ).order_by('display_order')
        attribute_data.append({
            'type': attr_type,
            'values': values,
        })

    context = {
        'product': product,
        'attribute_data': attribute_data,
    }
    return render(request, 'inventory/add_variant_to_product.html', context)


@login_required
def manage_attributes(request):
    """View and manage attribute types and values."""
    attribute_types = AttributeType.objects.prefetch_related('values').all()

    if request.method == 'POST':
        form = AddAttributeValueForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Attribute value added successfully.')
            return redirect('manage_attributes')
    else:
        form = AddAttributeValueForm()

    context = {
        'attribute_types': attribute_types,
        'form': form,
    }
    return render(request, 'inventory/manage_attributes.html', context)


@login_required
@require_POST
def add_attribute_value_ajax(request):
    """AJAX endpoint to add a new attribute value."""
    import json

    # Handle both JSON and form data
    if request.content_type == 'application/json':
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'success': False, 'error': 'Invalid JSON'})
    else:
        data = request.POST

    attr_type_ref = data.get('attribute_type')
    value = data.get('value', '').strip()
    display_value = data.get('display_value', '').strip()
    color_code = data.get('color_code', '').strip()

    if not attr_type_ref or not value:
        return JsonResponse({'success': False, 'error': 'Missing required fields'})

    try:
        # Support both ID and name for attribute_type
        if str(attr_type_ref).isdigit():
            attr_type = AttributeType.objects.get(id=int(attr_type_ref))
        else:
            attr_type = AttributeType.objects.get(name__iexact=attr_type_ref)

        # Check if value already exists
        if AttributeValue.objects.filter(attribute_type=attr_type, value=value).exists():
            return JsonResponse({'success': False, 'error': 'This value already exists'})

        # Get max display order
        max_order = AttributeValue.objects.filter(attribute_type=attr_type).aggregate(
            max_order=Max('display_order')
        )['max_order'] or 0

        attr_value = AttributeValue.objects.create(
            attribute_type=attr_type,
            value=value,
            display_value=display_value or value,
            color_code=color_code if attr_type.name == 'Color' else '',
            display_order=max_order + 1,
            is_active=True,
        )

        return JsonResponse({
            'success': True,
            'id': attr_value.id,
            'value': attr_value.value,
            'display_value': attr_value.display_value or attr_value.value,
            'color_code': attr_value.color_code,
        })

    except AttributeType.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Invalid attribute type'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def get_variant_stock_ajax(request, pk):
    """AJAX endpoint to get variant stock for POS."""
    product = get_object_or_404(Inventory, pk=pk)

    if not product.has_variants:
        return JsonResponse({
            'has_variants': False,
            'stock': product.quantity_in_Stock,
            'price': float(product.selling_price or 0),
        })

    # Get all variants with their attributes
    variants = product.variants.filter(is_active=True).prefetch_related('attribute_values')

    # Get attribute types for this product
    attribute_types = list(product.variant_attributes.filter(is_active=True).order_by('display_order'))

    # Build attribute values available for selection
    attributes = {}
    for attr_type in attribute_types:
        values = AttributeValue.objects.filter(
            attribute_type=attr_type,
            is_active=True,
            variants__product=product,
            variants__is_active=True
        ).distinct().order_by('display_order')

        attributes[attr_type.name] = [{
            'id': v.id,
            'value': v.value,
            'display': v.display_value or v.value,
            'color_code': v.color_code,
        } for v in values]

    # Build variants data
    variants_data = []
    for variant in variants:
        attr_ids = {str(av.attribute_type_id): av.id for av in variant.attribute_values.all()}
        variants_data.append({
            'id': variant.id,
            'sku': variant.sku,
            'attribute_ids': attr_ids,
            'attrs_display': variant.attribute_string,
            'stock': variant.quantity_in_stock,
            'price': float(variant.effective_selling_price),
            'purchase_price': float(variant.effective_purchase_price),
        })

    return JsonResponse({
        'has_variants': True,
        'attribute_types': [{'id': at.id, 'name': at.name, 'display_name': at.display_name} for at in attribute_types],
        'attributes': attributes,
        'variants': variants_data,
    })

