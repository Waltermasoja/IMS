from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.db import transaction
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.db.models import Sum, Q
from django.db.models.functions import TruncMonth
from decimal import Decimal

from .models import (
    CashbookEntry, BankReconciliation, GLAccount, JournalEntry, JournalLine,
    ARInvoice, ARPayment, LaybyPlan, LaybyItem, LaybyPayment
)
from .forms import (
    CashbookEntryForm, BankReconciliationForm, DateRangeForm,
    ARInvoiceForm, ARPaymentFormSimple, LaybyPlanForm, LaybyItemForm, LaybyPaymentFormSimple
)

# ==================== CASHBOOK VIEWS ====================

@login_required
def cashbook_list(request):
    """Display cashbook entries with running balance"""
    form = DateRangeForm(request.GET or None)
    qs = CashbookEntry.objects.all().order_by('date', 'id')

    start_date = end_date = None
    if form.is_valid():
        start_date = form.cleaned_data.get('start_date')
        end_date = form.cleaned_data.get('end_date')
        if start_date:
            qs = qs.filter(date__gte=start_date)
        if end_date:
            qs = qs.filter(date__lte=end_date)

    # Opening balance = sum before start_date
    opening = Decimal('0')
    if start_date:
        before = CashbookEntry.objects.filter(date__lt=start_date)
        opening = (before.aggregate(
            r=Sum('receipt_amount'), p=Sum('payment_amount')
        )['r'] or 0) - (before.aggregate(
            r=Sum('receipt_amount'), p=Sum('payment_amount')
        )['p'] or 0)

    totals = qs.aggregate(r=Sum('receipt_amount'), p=Sum('payment_amount'))
    receipts = totals['r'] or 0
    payments = totals['p'] or 0
    closing = opening + receipts - payments

    # Build running balance rows
    running = opening
    rows = []
    for e in qs:
        running += (e.receipt_amount or 0) - (e.payment_amount or 0)
        rows.append({'entry': e, 'running': running})

    return render(request, 'accounting/cashbook_list.html', {
        'form': form,
        'rows': rows,
        'opening': opening,
        'receipts': receipts,
        'payments': payments,
        'closing': closing,
    })


@login_required
def cashbook_add(request):
    """Add new cashbook entry"""
    if request.method == 'POST':
        form = CashbookEntryForm(request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.recorded_by = request.user
            obj.save()
            messages.success(request, 'Cashbook entry recorded')
            return redirect('accounting:cashbook_list')
    else:
        form = CashbookEntryForm()
    return render(request, 'accounting/cashbook_form.html', {'form': form})


@login_required
def cashflow_report(request):
    """Monthly cashflow report"""
    # Monthly summary of receipts/payments
    qs = CashbookEntry.objects.all()
    monthly = (qs
        .annotate(month=TruncMonth('date'))
        .values('month')
        .annotate(
            receipts=Sum('receipt_amount'),
            payments=Sum('payment_amount')
        )
        .order_by('month'))

    rows = []
    for m in monthly:
        r = float(m['receipts'] or 0)
        p = float(m['payments'] or 0)
        rows.append({
            'month': m['month'],
            'receipts': r,
            'payments': p,
            'net': r - p,
        })

    return render(request, 'accounting/cashflow_report.html', {'rows': rows})

# ==================== BANK RECONCILIATION ====================

@login_required
def bank_reconciliation_list(request):
    """List all bank reconciliations"""
    reconciliations = BankReconciliation.objects.all().order_by('-month')
    return render(request, 'accounting/bank_reconciliation_list.html', {
        'reconciliations': reconciliations
    })

@login_required
def bank_reconciliation_add(request):
    """Add new bank reconciliation"""
    if request.method == 'POST':
        form = BankReconciliationForm(request.POST)
        if form.is_valid():
            reconciliation = form.save(commit=False)
            # Calculate difference
            reconciliation.difference = reconciliation.bank_statement_balance - reconciliation.closing_balance
            reconciliation.save()
            messages.success(request, 'Bank reconciliation created')
            return redirect('accounting:bank_reconciliation_list')
    else:
        form = BankReconciliationForm()
    
    return render(request, 'accounting/bank_reconciliation_form.html', {'form': form})

# ==================== ACCOUNTS RECEIVABLE ====================

@login_required
def ar_invoice_list(request):
    """List all A/R invoices"""
    invoices = ARInvoice.objects.all().select_related('customer').order_by('-invoice_date')
    return render(request, 'accounting/ar_invoice_list.html', {
        'invoices': invoices
    })

@login_required
def ar_invoice_detail(request, invoice_id):
    """A/R invoice detail with payment history"""
    invoice = get_object_or_404(ARInvoice, pk=invoice_id)
    payments = invoice.payments.all().order_by('-payment_date')
    
    return render(request, 'accounting/ar_invoice_detail.html', {
        'invoice': invoice,
        'payments': payments,
    })

@login_required
def ar_payment_add(request, invoice_id=None):
    """Add payment to A/R invoice"""
    invoice = None
    if invoice_id:
        invoice = get_object_or_404(ARInvoice, pk=invoice_id)
    
    if request.method == 'POST':
        form = ARPaymentFormSimple(request.POST)
        if form.is_valid():
            payment = form.save(commit=False)
            payment.recorded_by = request.user
            payment.save()
            messages.success(request, f'Payment of {payment.amount} recorded')
            return redirect('accounting:ar_invoice_detail', invoice_id=payment.invoice.id)
    else:
        initial = {}
        if invoice:
            initial['invoice'] = invoice
        form = ARPaymentFormSimple(initial=initial)
    
    return render(request, 'accounting/ar_payment_form.html', {
        'form': form,
        'invoice': invoice,
    })

# ==================== LAYBY MANAGEMENT ====================

@login_required
def layby_list(request):
    """List all layby plans"""
    plans = LaybyPlan.objects.all().select_related('customer').order_by('-created_date')
    return render(request, 'accounting/layby_list.html', {
        'plans': plans
    })

@login_required
def layby_detail(request, plan_id):
    """Layby plan detail with items and payments"""
    plan = get_object_or_404(LaybyPlan, pk=plan_id)
    items = plan.items.all().select_related('inventory_item')
    payments = plan.payments.all().order_by('-payment_date')
    
    return render(request, 'accounting/layby_detail.html', {
        'plan': plan,
        'items': items,
        'payments': payments,
    })

@login_required
def layby_payment_add(request, plan_id):
    """Add payment to layby plan"""
    plan = get_object_or_404(LaybyPlan, pk=plan_id)
    
    if request.method == 'POST':
        form = LaybyPaymentFormSimple(request.POST)
        if form.is_valid():
            payment = form.save(commit=False)
            payment.recorded_by = request.user
            payment.save()
            messages.success(request, f'Layby payment of {payment.amount} recorded')
            return redirect('accounting:layby_detail', plan_id=plan.id)
    else:
        form = LaybyPaymentFormSimple(initial={'plan': plan})
    
    return render(request, 'accounting/layby_payment_form.html', {
        'form': form,
        'plan': plan,
    })

# ==================== DASHBOARD ====================

@login_required
def accounting_dashboard(request):
    """Accounting dashboard with key metrics"""
    # Current cash balance
    cashbook_balance = CashbookEntry.objects.aggregate(
        receipts=Sum('receipt_amount'),
        payments=Sum('payment_amount')
    )
    cash_balance = (cashbook_balance['receipts'] or 0) - (cashbook_balance['payments'] or 0)
    
    # Outstanding A/R
    outstanding_ar = ARInvoice.objects.filter(status__in=['PENDING', 'PARTIAL', 'OVERDUE']).aggregate(
        total=Sum('total_amount'),
        paid=Sum('amount_paid')
    )
    ar_outstanding = (outstanding_ar['total'] or 0) - (outstanding_ar['paid'] or 0)
    
    # Active layby balance
    active_laybys = LaybyPlan.objects.filter(status='ACTIVE').aggregate(
        total=Sum('total_price'),
        paid=Sum('amount_paid')
    )
    layby_outstanding = (active_laybys['total'] or 0) - (active_laybys['paid'] or 0)
    
    # Recent transactions
    recent_cashbook = CashbookEntry.objects.all().order_by('-created_date')[:10]
    recent_ar_payments = ARPayment.objects.all().select_related('invoice__customer').order_by('-created_date')[:10]
    
    context = {
        'cash_balance': cash_balance,
        'ar_outstanding': ar_outstanding,
        'layby_outstanding': layby_outstanding,
        'recent_cashbook': recent_cashbook,
        'recent_ar_payments': recent_ar_payments,
    }
    
    return render(request, 'accounting/dashboard.html', context)
