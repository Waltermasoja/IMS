from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.db import transaction
from django.views.decorators.http import require_POST
from django.utils import timezone
from decimal import Decimal

from .models import (
    SalesInvoice, SalesInvoiceItem, Sales, Customer, Inventory
)
from .forms import CustomerForm, QuickCustomerForm


@login_required
def invoice_list(request):
    """List all sales invoices with filtering options"""
    invoices = SalesInvoice.objects.all().select_related('customer', 'created_by')
    
    # Filter by customer
    customer_id = request.GET.get('customer')
    if customer_id:
        invoices = invoices.filter(customer_id=customer_id)
    
    # Filter by date range
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    if start_date:
        invoices = invoices.filter(invoice_date__gte=start_date)
    if end_date:
        invoices = invoices.filter(invoice_date__lte=end_date)
    
    # Filter by email sent status
    email_filter = request.GET.get('email_sent')
    if email_filter == 'yes':
        invoices = invoices.filter(email_sent=True)
    elif email_filter == 'no':
        invoices = invoices.filter(email_sent=False)
    
    context = {
        'invoices': invoices,
        'customers': Customer.objects.all().order_by('name'),
    }
    return render(request, 'inventory/invoice_list.html', context)


@login_required
def invoice_detail(request, invoice_id):
    """View a single invoice with all details"""
    invoice = get_object_or_404(
        SalesInvoice.objects.select_related('customer', 'created_by'),
        pk=invoice_id
    )
    items = invoice.items.all().select_related('sale__inventory_item')
    
    context = {
        'invoice': invoice,
        'items': items,
    }
    return render(request, 'inventory/invoice_detail.html', context)


@login_required
def generate_invoice_from_sales(request):
    """Generate an invoice from selected sales or create a new one"""
    if request.method == 'POST':
        sale_ids = request.POST.getlist('sale_ids')
        customer_id = request.POST.get('customer_id')
        add_new_customer = request.POST.get('add_new_customer') == 'on'
        
        try:
            with transaction.atomic():
                # Handle customer
                customer = None
                if add_new_customer:
                    # Create new customer
                    customer_form = QuickCustomerForm(request.POST)
                    if customer_form.is_valid():
                        customer = customer_form.save()
                    else:
                        messages.error(request, 'Invalid customer information')
                        return redirect('sales_history')
                elif customer_id:
                    customer = Customer.objects.get(pk=customer_id)
                
                # Get selected sales
                sales = Sales.objects.filter(id__in=sale_ids).select_related('inventory_item')
                
                if not sales.exists():
                    messages.error(request, 'No sales selected')
                    return redirect('sales_history')
                
                # Calculate totals
                subtotal = sum(sale.total_amount for sale in sales)
                discount_amount = sum(
                    (sale.sale_price * sale.quantity_sold * sale.discount_applied / 100)
                    for sale in sales
                )
                
                # Create invoice
                invoice = SalesInvoice.objects.create(
                    customer=customer,
                    subtotal=subtotal,
                    discount_amount=discount_amount,
                    total_amount=subtotal,
                    created_by=request.user
                )
                
                # Create invoice items
                for sale in sales:
                    SalesInvoiceItem.objects.create(
                        invoice=invoice,
                        sale=sale,
                        product_name=sale.inventory_item.name,
                        product_code=sale.inventory_item.product_code,
                        quantity=sale.quantity_sold,
                        unit_price=sale.sale_price,
                        discount_percent=sale.discount_applied,
                        line_total=sale.total_amount
                    )
                
                # Update customer purchase count if customer exists
                if customer:
                    customer.purchase_count += 1
                    customer.save(update_fields=['purchase_count'])
                    
                    # Auto-send email if opted in
                    if customer.opt_in_for_emails and customer.email:
                        if invoice.send_email():
                            messages.success(
                                request, 
                                f'Invoice {invoice.invoice_number} created and emailed to {customer.email}'
                            )
                        else:
                            messages.warning(
                                request,
                                f'Invoice {invoice.invoice_number} created but email failed to send'
                            )
                    else:
                        messages.success(request, f'Invoice {invoice.invoice_number} created successfully')
                else:
                    messages.success(request, f'Invoice {invoice.invoice_number} created for walk-in customer')
                
                return redirect('invoice_detail', invoice_id=invoice.id)
                
        except Customer.DoesNotExist:
            messages.error(request, 'Selected customer not found')
            return redirect('sales_history')
        except Exception as e:
            messages.error(request, f'Error creating invoice: {str(e)}')
            return redirect('sales_history')
    
    # GET request: show form
    recent_sales = Sales.objects.filter(
        sale_date__gte=timezone.now() - timezone.timedelta(days=30)
    ).select_related('inventory_item', 'customer').order_by('-sale_date')[:50]
    
    customers = Customer.objects.filter(status='ACTIVE').order_by('name')
    
    context = {
        'recent_sales': recent_sales,
        'customers': customers,
        'customer_form': QuickCustomerForm(),
    }
    return render(request, 'inventory/generate_invoice.html', context)


@login_required
@require_POST
def send_invoice_email(request, invoice_id):
    """Send an invoice via email"""
    invoice = get_object_or_404(SalesInvoice, pk=invoice_id)
    
    if not invoice.customer:
        return JsonResponse({
            'success': False,
            'error': 'No customer associated with this invoice'
        })
    
    if not invoice.customer.opt_in_for_emails:
        return JsonResponse({
            'success': False,
            'error': 'Customer has not opted in for email invoices'
        })
    
    if not invoice.customer.email:
        return JsonResponse({
            'success': False,
            'error': 'Customer has no email address on file'
        })
    
    success = invoice.send_email()
    
    if success:
        return JsonResponse({
            'success': True,
            'message': f'Invoice emailed to {invoice.customer.email}'
        })
    else:
        return JsonResponse({
            'success': False,
            'error': 'Failed to send email. Please check email configuration.'
        })


@login_required
def print_invoice(request, invoice_id):
    """Generate a printable version of the invoice"""
    invoice = get_object_or_404(
        SalesInvoice.objects.select_related('customer', 'created_by'),
        pk=invoice_id
    )
    items = invoice.items.all().select_related('sale__inventory_item')
    
    context = {
        'invoice': invoice,
        'items': items,
        'print_mode': True,
    }
    return render(request, 'inventory/invoice_print.html', context)


@login_required
def customer_invoices(request, customer_id):
    """View all invoices for a specific customer"""
    customer = get_object_or_404(Customer, pk=customer_id)
    invoices = SalesInvoice.objects.filter(customer=customer).order_by('-invoice_date')
    
    context = {
        'customer': customer,
        'invoices': invoices,
    }
    return render(request, 'inventory/customer_invoices.html', context)
