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
@login_required
@require_POST
def layby_fulfill_action(request, plan_id):
    """Fulfill a layby plan: recognize revenue and COGS; update related sales rows."""
    plan = get_object_or_404(LaybyPlan, pk=plan_id)
    from inventory.models import Sales
    
    if plan.status != 'ACTIVE':
        messages.error(request, 'Plan not active')
        return redirect('accounting:layby_list')

    with transaction.atomic():
        # Recognize revenue from unearned to sales revenue, and COGS
        try:
            unearned = GLAccount.objects.get(code='2300')  # Unearned Revenue
            revenue = GLAccount.objects.get(code='4000')   # Sales Revenue
            cogs_acct = GLAccount.objects.get(code='5000') # Cost of Goods Sold
            inventory = GLAccount.objects.get(code='1300') # Inventory Asset

            je = JournalEntry.objects.create(
                memo=f'Layby fulfillment plan#{plan.id}',
                created_by=request.user
            )
            
            # Dr Unearned Revenue, Cr Sales Revenue
            JournalLine.objects.create(
                entry=je,
                account=unearned,
                debit=plan.total_price,
                description='Recognize revenue from layby'
            )
            JournalLine.objects.create(
                entry=je,
                account=revenue,
                credit=plan.total_price,
                description='Sales revenue recognized',
                customer=plan.customer
            )

            # Calculate and post COGS
            total_cogs = Decimal('0')
            for item in plan.items.select_related('inventory_item'):
                cogs_amount = (item.inventory_item.purchase_price or Decimal('0')) * (item.quantity or 0)
                total_cogs += cogs_amount
            
            if total_cogs > 0:
                # Dr COGS, Cr Inventory
                JournalLine.objects.create(
                    entry=je,
                    account=cogs_acct,
                    debit=total_cogs,
                    description='Cost of goods sold'
                )
                JournalLine.objects.create(
                    entry=je,
                    account=inventory,
                    credit=total_cogs,
                    description='Inventory reduction'
                )
        except GLAccount.DoesNotExist:
            messages.warning(request, 'GL accounts not configured - journal entries skipped')

        # Mark plan as fulfilled
        plan.status = 'FULFILLED'
        plan.save(update_fields=['status'])

        # Update related Sales entries to mark as fulfilled (keep LAYBY for reporting)
        try:
            updated = 0
            for item in plan.items.select_related('inventory_item'):
                # Mark the sale as posted to GL to prevent duplicate postings
                qs = Sales.objects.filter(
                    inventory_item=item.inventory_item,
                    customer=plan.customer,
                    payment_method='LAYBY',
                    posted_to_gl=False
                )
                updated += qs.update(posted_to_gl=True)
            if updated:
                print(f"[LAYBY] Fulfill plan#{plan.id}: marked {updated} sales rows as posted to GL")
        except Exception as e:
            print(f"[LAYBY] Warning updating sales: {e}")

    messages.success(request, f'Layby plan #{plan.id} fulfilled - revenue recognized')
    return redirect('accounting:layby_list')


@login_required
@require_POST
def layby_cancel_action(request, plan_id):
    """Cancel a layby plan: restock and post refund/forfeit fee."""
    plan = get_object_or_404(LaybyPlan, pk=plan_id)
    from inventory.models import StockMovement
    fee = Decimal(request.POST.get('cancellation_fee', '0') or '0')

    for item in plan.items.select_related('inventory_item'):
        inv = item.inventory_item
        inv.quantity_in_Stock += item.quantity
        inv.save(update_fields=['quantity_in_Stock'])
        StockMovement.objects.create(
            inventory_item=inv,
            movement_type='IN',
            quantity=item.quantity,
            reason=f'Layby cancel plan#{plan.id}'
        )

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
    messages.success(request, f'Layby plan #{plan.id} cancelled')
    return redirect('accounting:layby_list')
from .expense_forms import ExpenseForm
from .models import Expense

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

# ==================== EXPENSES ====================

@login_required
def expense_list(request):
    expenses = Expense.objects.all().order_by('-date', '-id')
    return render(request, 'accounting/expense_list.html', {'expenses': expenses})

@login_required
def expense_add(request):
    if request.method == 'POST':
        form = ExpenseForm(request.POST)
        if form.is_valid():
            exp = form.save(commit=False)
            exp.recorded_by = request.user
            exp.save()
            messages.success(request, 'Expense recorded')
            return redirect('accounting:expense_list')
    else:
        form = ExpenseForm()
    return render(request, 'accounting/expense_form.html', {'form': form})

# ==================== DASHBOARD ====================

@login_required
def accounting_dashboard(request):
    """Enhanced Financial Dashboard with key business metrics"""
    from inventory.models import Inventory, SupplierInvoice, Sales
    from django.db.models import F
    from datetime import datetime, timedelta

    # === CASH ===
    try:
        cash_account = GLAccount.objects.get(code='1000')
        cash_balance = cash_account.balance
    except GLAccount.DoesNotExist:
        cashbook_balance = CashbookEntry.objects.aggregate(
            receipts=Sum('receipt_amount'),
            payments=Sum('payment_amount')
        )
        cash_balance = Decimal(str((cashbook_balance['receipts'] or 0) - (cashbook_balance['payments'] or 0)))

    # === ACCOUNTS RECEIVABLE ===
    try:
        ar_account = GLAccount.objects.get(code='1200')
        ar_outstanding = ar_account.balance
    except GLAccount.DoesNotExist:
        outstanding_ar = ARInvoice.objects.filter(status__in=['PENDING', 'PARTIAL', 'OVERDUE']).aggregate(
            total=Sum('total_amount'),
            paid=Sum('amount_paid')
        )
        ar_outstanding = Decimal(str((outstanding_ar['total'] or 0) - (outstanding_ar['paid'] or 0)))

    # === ACCOUNTS PAYABLE ===
    ap_outstanding = SupplierInvoice.objects.filter(paid=False).aggregate(
        total=Sum(F('invoice_amount') - F('amount_paid'))
    )['total'] or Decimal('0')

    # === INVENTORY VALUE ===
    try:
        inventory_account = GLAccount.objects.get(code='1300')
        inventory_value = inventory_account.balance
    except GLAccount.DoesNotExist:
        inventory_value = Inventory.objects.aggregate(
            total=Sum(F('quantity_in_Stock') * F('purchase_price'))
        )['total'] or Decimal('0')

    # === TOTAL ASSETS ===
    total_assets = cash_balance + ar_outstanding + inventory_value

    # === LAYBY DEPOSITS (Liability) ===
    try:
        unearned_account = GLAccount.objects.get(code='2300')
        layby_deposits = unearned_account.balance
    except GLAccount.DoesNotExist:
        active_laybys = LaybyPlan.objects.filter(status='ACTIVE').aggregate(
            paid=Sum('amount_paid')
        )
        layby_deposits = Decimal(str(active_laybys['paid'] or 0))

    # === THIS MONTH'S METRICS ===
    now = timezone.now()
    month_start = datetime(now.year, now.month, 1)
    month_start = timezone.make_aware(month_start)

    # This month's sales revenue
    month_sales = Sales.objects.filter(
        sale_date__gte=month_start,
        posted_to_gl=True
    ).aggregate(total=Sum('total_amount'))['total'] or Decimal('0')

    # This month's profit (simplified)
    try:
        revenue_account = GLAccount.objects.get(code='4000')
        cogs_account = GLAccount.objects.get(code='5000')

        # Get transactions for this month
        month_revenue = JournalLine.objects.filter(
            entry__entry_date__gte=month_start,
            account=revenue_account,
            credit__gt=0
        ).aggregate(total=Sum('credit'))['total'] or Decimal('0')

        month_cogs = JournalLine.objects.filter(
            entry__entry_date__gte=month_start,
            account=cogs_account,
            debit__gt=0
        ).aggregate(total=Sum('debit'))['total'] or Decimal('0')

        month_profit = month_revenue - month_cogs
    except GLAccount.DoesNotExist:
        month_profit = Decimal('0')

    # === OWNER'S EQUITY ===
    total_liabilities = layby_deposits + ap_outstanding
    owners_equity = total_assets - total_liabilities

    # Recent transactions
    recent_cashbook = CashbookEntry.objects.all().order_by('-date', '-created_date')[:5]
    recent_ar_payments = ARPayment.objects.all().select_related('invoice__customer').order_by('-created_date')[:5]

    # Quick stats
    low_stock_count = Inventory.objects.filter(quantity_in_Stock__lte=10, quantity_in_Stock__gt=0).count()
    out_of_stock_count = Inventory.objects.filter(quantity_in_Stock=0).count()

    context = {
        'cash_balance': cash_balance,
        'ar_outstanding': ar_outstanding,
        'ap_outstanding': ap_outstanding,
        'inventory_value': inventory_value,
        'total_assets': total_assets,
        'layby_deposits': layby_deposits,
        'total_liabilities': total_liabilities,
        'owners_equity': owners_equity,
        'month_sales': month_sales,
        'month_profit': month_profit,
        'recent_cashbook': recent_cashbook,
        'recent_ar_payments': recent_ar_payments,
        'low_stock_count': low_stock_count,
        'out_of_stock_count': out_of_stock_count,
    }

    return render(request, 'accounting/dashboard.html', context)


# ==================== AR REPORTS ====================

@login_required
def ar_aging_report(request):
    """Accounts Receivable Aging Report - shows outstanding invoices by age brackets."""
    from inventory.models import Customer
    from datetime import date

    # Get all outstanding AR invoices
    invoices = ARInvoice.objects.exclude(status='PAID').select_related('customer').order_by('invoice_date')

    # Filter by customer if specified
    customer_id = request.GET.get('customer')
    if customer_id:
        invoices = invoices.filter(customer_id=customer_id)

    # Age brackets
    today = date.today()
    aging_data = []

    for invoice in invoices:
        days_outstanding = (today - invoice.invoice_date).days
        outstanding = invoice.outstanding_amount

        # Determine age bracket
        if days_outstanding <= 30:
            bracket = '0-30'
        elif days_outstanding <= 60:
            bracket = '31-60'
        elif days_outstanding <= 90:
            bracket = '61-90'
        else:
            bracket = '90+'

        aging_data.append({
            'invoice': invoice,
            'days_outstanding': days_outstanding,
            'outstanding': outstanding,
            'bracket': bracket,
            'is_overdue': invoice.is_overdue,
        })

    # Calculate bracket totals
    brackets = {
        '0-30': Decimal('0'),
        '31-60': Decimal('0'),
        '61-90': Decimal('0'),
        '90+': Decimal('0'),
    }

    for data in aging_data:
        brackets[data['bracket']] += data['outstanding']

    total_outstanding = sum(brackets.values())

    # Calculate percentages
    bracket_percentages = {}
    for bracket, amount in brackets.items():
        if total_outstanding > 0:
            bracket_percentages[bracket] = (amount / total_outstanding * 100)
        else:
            bracket_percentages[bracket] = 0

    # Create template-friendly versions (for accessing in templates)
    brackets_list = [
        {'label': '0-30', 'amount': brackets['0-30'], 'percentage': bracket_percentages['0-30']},
        {'label': '31-60', 'amount': brackets['31-60'], 'percentage': bracket_percentages['31-60']},
        {'label': '61-90', 'amount': brackets['61-90'], 'percentage': bracket_percentages['61-90']},
        {'label': '90+', 'amount': brackets['90+'], 'percentage': bracket_percentages['90+']},
    ]

    # Get customers for filter
    customers = Customer.objects.filter(credit_limit__gt=0).order_by('name')

    context = {
        'aging_data': aging_data,
        'brackets_list': brackets_list,
        'total_outstanding': total_outstanding,
        'customers': customers,
        'selected_customer': customer_id or '',
    }

    return render(request, 'accounting/ar_aging_report.html', context)


@login_required
def customer_credit_utilization_report(request):
    """Report showing customer credit limits and utilization."""
    from inventory.models import Customer

    # Get all customers with credit limits
    customers = Customer.objects.filter(credit_limit__gt=0).order_by('-current_balance')

    utilization_data = []
    for customer in customers:
        available_credit = customer.credit_limit - customer.current_balance
        if customer.credit_limit > 0:
            utilization_percent = (customer.current_balance / customer.credit_limit) * 100
        else:
            utilization_percent = 0

        # Determine status
        if customer.current_balance > customer.credit_limit:
            status = 'over_limit'
        elif utilization_percent >= 90:
            status = 'high'
        elif utilization_percent >= 75:
            status = 'medium'
        else:
            status = 'good'

        utilization_data.append({
            'customer': customer,
            'credit_limit': customer.credit_limit,
            'current_balance': customer.current_balance,
            'available_credit': available_credit,
            'utilization_percent': round(utilization_percent, 1),
            'status': status,
        })

    # Sort by utilization (highest first)
    utilization_data.sort(key=lambda x: -x['utilization_percent'])

    # Summary stats
    total_credit_limit = sum(d['credit_limit'] for d in utilization_data)
    total_outstanding = sum(d['current_balance'] for d in utilization_data)
    over_limit_count = sum(1 for d in utilization_data if d['status'] == 'over_limit')
    high_utilization_count = sum(1 for d in utilization_data if d['status'] in ['over_limit', 'high'])

    context = {
        'utilization_data': utilization_data,
        'total_credit_limit': total_credit_limit,
        'total_outstanding': total_outstanding,
        'over_limit_count': over_limit_count,
        'high_utilization_count': high_utilization_count,
    }

    return render(request, 'accounting/customer_credit_utilization_report.html', context)


@login_required
def credit_sales_summary_report(request):
    """Summary of credit sales and collection performance."""
    from inventory.models import Sales, Customer
    from datetime import timedelta

    form = DateRangeForm(request.GET or None)

    # Default to last 30 days
    end_date = timezone.now()
    start_date = end_date - timedelta(days=30)

    if form.is_valid():
        if form.cleaned_data.get('start_date'):
            from datetime import datetime
            start_date = timezone.make_aware(datetime.combine(form.cleaned_data['start_date'], datetime.min.time()))
        if form.cleaned_data.get('end_date'):
            from datetime import datetime
            end_date = timezone.make_aware(datetime.combine(form.cleaned_data['end_date'], datetime.max.time()))

    # Get credit sales in period
    credit_sales = Sales.objects.filter(
        payment_method='CREDIT',
        sale_date__range=(start_date, end_date)
    ).select_related('customer')

    # Filter by customer if specified
    customer_id = request.GET.get('customer')
    if customer_id:
        credit_sales = credit_sales.filter(customer_id=customer_id)

    # Calculate metrics
    total_credit_sales = credit_sales.aggregate(total=Sum('total_amount'))['total'] or Decimal('0')
    total_sales_count = credit_sales.count()

    # Get outstanding AR
    outstanding_invoices = ARInvoice.objects.exclude(status='PAID')
    if customer_id:
        outstanding_invoices = outstanding_invoices.filter(customer_id=customer_id)

    total_ar_outstanding = outstanding_invoices.aggregate(
        total=Sum('total_amount') - Sum('amount_paid')
    )
    ar_outstanding = (outstanding_invoices.aggregate(total=Sum('total_amount'))['total'] or 0) - \
                     (outstanding_invoices.aggregate(paid=Sum('amount_paid'))['paid'] or 0)

    # Get payments in period
    ar_payments = ARPayment.objects.filter(
        payment_date__range=(start_date.date(), end_date.date())
    )
    if customer_id:
        ar_payments = ar_payments.filter(invoice__customer_id=customer_id)

    total_payments = ar_payments.aggregate(total=Sum('amount'))['total'] or Decimal('0')

    # Collection rate
    if total_credit_sales > 0:
        collection_rate = (total_payments / total_credit_sales) * 100
    else:
        collection_rate = 0

    # Average days to pay (simplified - using overdue invoices)
    overdue_invoices = outstanding_invoices.filter(status='OVERDUE')
    if overdue_invoices.exists():
        total_overdue_days = sum(
            (timezone.now().date() - inv.due_date).days
            for inv in overdue_invoices
        )
        avg_overdue_days = total_overdue_days / overdue_invoices.count()
    else:
        avg_overdue_days = 0

    # Customer breakdown
    if customer_id:
        customers_data = []
    else:
        customer_breakdown = credit_sales.values('customer__id', 'customer__name').annotate(
            total_sales=Sum('total_amount'),
            sales_count=Sum('id')
        ).order_by('-total_sales')[:10]

        customers_data = []
        for cb in customer_breakdown:
            if cb['customer__id']:
                cust = Customer.objects.get(id=cb['customer__id'])
                customers_data.append({
                    'customer': cust,
                    'total_sales': cb['total_sales'],
                    'current_balance': cust.current_balance,
                })

    # Get customers for filter
    customers = Customer.objects.filter(credit_limit__gt=0).order_by('name')

    context = {
        'form': form,
        'start_date': start_date,
        'end_date': end_date,
        'total_credit_sales': total_credit_sales,
        'total_sales_count': total_sales_count,
        'ar_outstanding': ar_outstanding,
        'total_payments': total_payments,
        'collection_rate': round(collection_rate, 1),
        'avg_overdue_days': round(avg_overdue_days, 1),
        'customers_data': customers_data,
        'customers': customers,
        'selected_customer': customer_id or '',
    }

    return render(request, 'accounting/credit_sales_summary_report.html', context)


# ==================== SIMPLE BUSINESS REPORTS ====================

@login_required
def daily_cash_summary(request):
    """Simple daily cash summary - professional view for daily operations."""
    from inventory.models import Sales
    from datetime import date, timedelta

    # Get date from query params or default to today
    selected_date_str = request.GET.get('date')
    if selected_date_str:
        from datetime import datetime
        selected_date = datetime.strptime(selected_date_str, '%Y-%m-%d').date()
    else:
        selected_date = date.today()

    # Previous day for comparison
    previous_date = selected_date - timedelta(days=1)

    # Cash receipts for the day
    cash_receipts = CashbookEntry.objects.filter(
        date=selected_date,
        receipt_amount__gt=0
    ).order_by('-receipt_amount')

    # Cash payments for the day
    cash_payments = CashbookEntry.objects.filter(
        date=selected_date,
        payment_amount__gt=0
    ).order_by('-payment_amount')

    # Totals
    total_receipts = cash_receipts.aggregate(total=Sum('receipt_amount'))['total'] or Decimal('0')
    total_payments = cash_payments.aggregate(total=Sum('payment_amount'))['total'] or Decimal('0')
    net_cash_today = total_receipts - total_payments

    # Calculate cash on hand (running balance)
    cash_before = CashbookEntry.objects.filter(date__lt=selected_date).aggregate(
        receipts=Sum('receipt_amount'),
        payments=Sum('payment_amount')
    )
    opening_balance = (cash_before['receipts'] or Decimal('0')) - (cash_before['payments'] or Decimal('0'))
    closing_balance = opening_balance + net_cash_today

    # Previous day for comparison
    prev_day_entries = CashbookEntry.objects.filter(date=previous_date).aggregate(
        receipts=Sum('receipt_amount'),
        payments=Sum('payment_amount')
    )
    prev_net = (prev_day_entries['receipts'] or Decimal('0')) - (prev_day_entries['payments'] or Decimal('0'))

    # Breakdown by category
    receipts_by_category = cash_receipts.values('category').annotate(
        total=Sum('receipt_amount')
    ).order_by('-total')

    payments_by_category = cash_payments.values('category').annotate(
        total=Sum('payment_amount')
    ).order_by('-total')

    # Sales breakdown for the day
    daily_sales = Sales.objects.filter(sale_date__date=selected_date)
    sales_summary = {
        'cash': daily_sales.filter(payment_method='CASH').aggregate(
            total=Sum('total_amount'),
            count=Sum('id')
        ),
        'credit': daily_sales.filter(payment_method='CREDIT').aggregate(
            total=Sum('total_amount'),
            count=Sum('id')
        ),
        'layby': daily_sales.filter(payment_method='LAYBY').aggregate(
            total=Sum('total_amount'),
            count=Sum('id')
        ),
    }

    # Alerts and action items
    alerts = []

    # Check for overdue AR invoices
    overdue_count = ARInvoice.objects.filter(status='OVERDUE').count()
    if overdue_count > 0:
        alerts.append({
            'type': 'warning',
            'message': f'{overdue_count} customer invoice(s) overdue',
            'action_url': '/accounting/ar/invoices/',
            'action_text': 'View Invoices'
        })

    # Check for customers over credit limit
    from inventory.models import Customer
    over_limit = Customer.objects.filter(
        current_balance__gt=models.F('credit_limit'),
        credit_limit__gt=0
    ).count()
    if over_limit > 0:
        alerts.append({
            'type': 'danger',
            'message': f'{over_limit} customer(s) over credit limit',
            'action_url': '/accounting/reports/customer-credit-utilization/',
            'action_text': 'Review Credits'
        })

    # Check for negative cash balance
    if closing_balance < 0:
        alerts.append({
            'type': 'danger',
            'message': 'Cash balance is negative',
            'action_url': '/accounting/cashbook/',
            'action_text': 'Review Cashbook'
        })

    # Check if no sales today
    if daily_sales.count() == 0 and selected_date == date.today():
        alerts.append({
            'type': 'info',
            'message': 'No sales recorded yet today',
            'action_url': '/pos/',
            'action_text': 'Go to POS'
        })

    context = {
        'selected_date': selected_date,
        'previous_date': previous_date,
        'is_today': selected_date == date.today(),

        # Main metrics
        'total_receipts': total_receipts,
        'total_payments': total_payments,
        'net_cash_today': net_cash_today,
        'opening_balance': opening_balance,
        'closing_balance': closing_balance,

        # Comparison
        'prev_net': prev_net,
        'change_from_yesterday': net_cash_today - prev_net,

        # Detailed lists
        'cash_receipts': cash_receipts,
        'cash_payments': cash_payments,
        'receipts_by_category': receipts_by_category,
        'payments_by_category': payments_by_category,

        # Sales breakdown
        'sales_summary': sales_summary,
        'total_sales': daily_sales.aggregate(total=Sum('total_amount'))['total'] or Decimal('0'),
        'sales_count': daily_sales.count(),

        # Alerts
        'alerts': alerts,
    }

    return render(request, 'accounting/daily_cash_summary.html', context)


@login_required
def profit_loss_report(request):
    """Monthly Profit & Loss statement - simple view with drill-down capability."""
    from inventory.models import Sales
    from datetime import datetime

    # Get month/year from query params or default to current month
    month_str = request.GET.get('month')
    year_str = request.GET.get('year')

    if month_str and year_str:
        month = int(month_str)
        year = int(year_str)
    else:
        now = timezone.now()
        month = now.month
        year = now.year

    # Date range for the month
    start_date = datetime(year, month, 1)
    if month == 12:
        end_date = datetime(year + 1, 1, 1)
    else:
        end_date = datetime(year, month + 1, 1)

    start_date = timezone.make_aware(start_date)
    end_date = timezone.make_aware(end_date)

    # REVENUE
    # Get all sales (cash + credit) posted to GL in this period
    sales_revenue = Sales.objects.filter(
        sale_date__range=(start_date, end_date),
        posted_to_gl=True
    ).aggregate(total=Sum('total_amount'))['total'] or Decimal('0')

    # Other income (layby forfeit fees, etc.)
    try:
        other_income_account = GLAccount.objects.get(code='4800')
        other_income = JournalLine.objects.filter(
            entry__entry_date__range=(start_date, end_date),
            account=other_income_account,
            credit__gt=0
        ).aggregate(total=Sum('credit'))['total'] or Decimal('0')
    except GLAccount.DoesNotExist:
        other_income = Decimal('0')

    total_revenue = sales_revenue + other_income

    # COST OF GOODS SOLD
    try:
        cogs_account = GLAccount.objects.get(code='5000')
        cogs = JournalLine.objects.filter(
            entry__entry_date__range=(start_date, end_date),
            account=cogs_account,
            debit__gt=0
        ).aggregate(total=Sum('debit'))['total'] or Decimal('0')
    except GLAccount.DoesNotExist:
        cogs = Decimal('0')

    # GROSS PROFIT
    gross_profit = total_revenue - cogs
    gross_margin = (gross_profit / total_revenue * 100) if total_revenue > 0 else Decimal('0')

    # OPERATING EXPENSES
    expense_categories = Expense.objects.filter(
        date__range=(start_date.date(), end_date.date())
    ).values('category').annotate(
        total=Sum('amount')
    ).order_by('-total')

    total_expenses = sum(cat['total'] for cat in expense_categories)

    # NET PROFIT
    net_profit = gross_profit - total_expenses
    net_margin = (net_profit / total_revenue * 100) if total_revenue > 0 else Decimal('0')

    # Previous month for comparison
    if month == 1:
        prev_month = 12
        prev_year = year - 1
    else:
        prev_month = month - 1
        prev_year = year

    prev_start = datetime(prev_year, prev_month, 1)
    if prev_month == 12:
        prev_end = datetime(prev_year + 1, 1, 1)
    else:
        prev_end = datetime(prev_year, prev_month + 1, 1)

    prev_start = timezone.make_aware(prev_start)
    prev_end = timezone.make_aware(prev_end)

    prev_revenue = Sales.objects.filter(
        sale_date__range=(prev_start, prev_end),
        posted_to_gl=True
    ).aggregate(total=Sum('total_amount'))['total'] or Decimal('0')

    # Generate month list for dropdown
    months = [
        {'value': i, 'name': calendar.month_name[i]}
        for i in range(1, 13)
    ]
    years = list(range(year - 2, year + 2))

    # Drill-down data (if requested)
    show_details = request.GET.get('details') == 'true'
    detail_data = {}

    if show_details:
        # Detailed expense breakdown
        detail_data['expense_details'] = Expense.objects.filter(
            date__range=(start_date.date(), end_date.date())
        ).select_related('gl_account').order_by('-amount')

        # Sales by payment method
        detail_data['sales_by_method'] = Sales.objects.filter(
            sale_date__range=(start_date, end_date),
            posted_to_gl=True
        ).values('payment_method').annotate(
            total=Sum('total_amount'),
            count=Sum('id')
        )

    context = {
        'month': month,
        'year': year,
        'month_name': calendar.month_name[month],
        'months': months,
        'years': years,

        # Revenue
        'sales_revenue': sales_revenue,
        'other_income': other_income,
        'total_revenue': total_revenue,

        # Costs
        'cogs': cogs,
        'gross_profit': gross_profit,
        'gross_margin': round(gross_margin, 1),

        # Expenses
        'expense_categories': expense_categories,
        'total_expenses': total_expenses,

        # Bottom line
        'net_profit': net_profit,
        'net_margin': round(net_margin, 1),

        # Comparison
        'prev_revenue': prev_revenue,
        'revenue_change': sales_revenue - prev_revenue,
        'revenue_change_percent': ((sales_revenue - prev_revenue) / prev_revenue * 100) if prev_revenue > 0 else Decimal('0'),

        # Drill-down
        'show_details': show_details,
        'detail_data': detail_data,
    }

    return render(request, 'accounting/profit_loss_report.html', context)


@login_required
def balance_sheet(request):
    """Simple Balance Sheet for small shop - Assets, Liabilities, Equity."""
    from inventory.models import Inventory, Customer
    from datetime import datetime

    # Get date from query params or default to today
    date_str = request.GET.get('as_of_date')
    if date_str:
        try:
            as_of_date = datetime.strptime(date_str, '%Y-%m-%d')
            as_of_date = timezone.make_aware(as_of_date)
        except ValueError:
            as_of_date = timezone.now()
    else:
        as_of_date = timezone.now()

    # === ASSETS ===

    # 1. Cash (GL Account 1000)
    try:
        cash_account = GLAccount.objects.get(code='1000')
        cash_balance = cash_account.balance
    except GLAccount.DoesNotExist:
        cash_balance = Decimal('0')

    # 2. Accounts Receivable (GL Account 1200)
    try:
        ar_account = GLAccount.objects.get(code='1200')
        ar_balance = ar_account.balance
    except GLAccount.DoesNotExist:
        ar_balance = Decimal('0')

    # 3. Inventory Value (GL Account 1300 or calculate from products)
    try:
        inventory_account = GLAccount.objects.get(code='1300')
        inventory_value = inventory_account.balance
    except GLAccount.DoesNotExist:
        # Fallback: Calculate from products (quantity × purchase_price)
        inventory_value = Inventory.objects.aggregate(
            total=Sum(F('quantity_in_Stock') * F('purchase_price'))
        )['total'] or Decimal('0')

    total_assets = cash_balance + ar_balance + inventory_value

    # === LIABILITIES ===

    # 1. Unearned Revenue / Customer Deposits (GL Account 2300 - layby deposits)
    try:
        unearned_rev_account = GLAccount.objects.get(code='2300')
        unearned_revenue = unearned_rev_account.balance
    except GLAccount.DoesNotExist:
        unearned_revenue = Decimal('0')

    # 2. Accounts Payable (what we owe suppliers)
    # Calculate from unpaid import order invoices
    from inventory.models import SupplierInvoice
    accounts_payable = SupplierInvoice.objects.filter(
        paid=False
    ).aggregate(
        total=Sum(F('invoice_amount') - F('amount_paid'))
    )['total'] or Decimal('0')

    total_liabilities = unearned_revenue + accounts_payable

    # === EQUITY ===
    # Owner's Equity = Assets - Liabilities
    owners_equity = total_assets - total_liabilities

    # Calculate this period's profit (to show as part of equity)
    # This is a simplified version - get from P&L
    try:
        revenue_account = GLAccount.objects.get(code='4000')
        cogs_account = GLAccount.objects.get(code='5000')

        # Simple profit = Revenue - COGS (not including operating expenses for simplicity)
        period_profit = revenue_account.balance - abs(cogs_account.balance)
    except GLAccount.DoesNotExist:
        period_profit = Decimal('0')

    context = {
        'as_of_date': as_of_date,
        'cash_balance': cash_balance,
        'ar_balance': ar_balance,
        'inventory_value': inventory_value,
        'total_assets': total_assets,
        'unearned_revenue': unearned_revenue,
        'accounts_payable': accounts_payable,
        'total_liabilities': total_liabilities,
        'owners_equity': owners_equity,
        'period_profit': period_profit,
        'retained_earnings': owners_equity - period_profit,  # Historical equity
    }

    return render(request, 'accounting/balance_sheet.html', context)


@login_required
def accounts_payable_list(request):
    """Simple Accounts Payable list - what we owe suppliers."""
    from inventory.models import SupplierInvoice, Supplier

    # Get all unpaid or partially paid invoices
    unpaid_invoices = SupplierInvoice.objects.filter(
        paid=False
    ).select_related('import_order__supplier').order_by('due_date')

    # Calculate totals
    total_outstanding = Decimal('0')
    overdue_amount = Decimal('0')
    today = timezone.now().date()

    supplier_summary = {}

    for invoice in unpaid_invoices:
        amount_due = invoice.invoice_amount - invoice.amount_paid

        # Add to supplier summary
        supplier_name = invoice.import_order.supplier.name if invoice.import_order and invoice.import_order.supplier else 'Unknown'
        if supplier_name not in supplier_summary:
            supplier_summary[supplier_name] = {'total': Decimal('0'), 'count': 0}

        supplier_summary[supplier_name]['total'] += amount_due
        supplier_summary[supplier_name]['count'] += 1

        total_outstanding += amount_due

        # Check if overdue
        if invoice.due_date and invoice.due_date < today:
            overdue_amount += amount_due

    # Convert to list for template
    supplier_list = [
        {'name': name, 'total': data['total'], 'count': data['count']}
        for name, data in supplier_summary.items()
    ]
    supplier_list.sort(key=lambda x: x['total'], reverse=True)

    context = {
        'invoices': unpaid_invoices,
        'total_outstanding': total_outstanding,
        'overdue_amount': overdue_amount,
        'supplier_summary': supplier_list,
        'invoice_count': unpaid_invoices.count(),
    }

    return render(request, 'accounting/accounts_payable_list.html', context)


@login_required
def customer_statement(request, customer_id):
    """Customer account statement - shows transaction history and balance."""
    from inventory.models import Customer

    customer = get_object_or_404(Customer, pk=customer_id)

    # Date range filter
    form = DateRangeForm(request.GET or None)
    start_date = end_date = None

    if form.is_valid():
        start_date = form.cleaned_data.get('start_date')
        end_date = form.cleaned_data.get('end_date')

    # Get all transactions for this customer
    transactions = []

    # AR Invoices (debits - customer owes us)
    invoices = ARInvoice.objects.filter(customer=customer)
    if start_date:
        invoices = invoices.filter(invoice_date__gte=start_date)
    if end_date:
        invoices = invoices.filter(invoice_date__lte=end_date)

    for invoice in invoices:
        transactions.append({
            'date': invoice.invoice_date,
            'type': 'Invoice',
            'reference': invoice.invoice_number,
            'description': f'Credit sale - Invoice {invoice.invoice_number}',
            'debit': invoice.total_amount,
            'credit': Decimal('0'),
            'related_object': invoice,
        })

    # AR Payments (credits - customer paid us)
    payments = ARPayment.objects.filter(invoice__customer=customer)
    if start_date:
        payments = payments.filter(payment_date__gte=start_date)
    if end_date:
        payments = payments.filter(payment_date__lte=end_date)

    for payment in payments:
        transactions.append({
            'date': payment.payment_date,
            'type': 'Payment',
            'reference': payment.reference or f'Payment #{payment.id}',
            'description': f'Payment received - {payment.get_method_display()}',
            'debit': Decimal('0'),
            'credit': payment.amount,
            'related_object': payment,
        })

    # Sort by date
    transactions.sort(key=lambda x: x['date'])

    # Calculate running balance
    running_balance = Decimal('0')
    for trans in transactions:
        running_balance += trans['debit'] - trans['credit']
        trans['balance'] = running_balance

    # Summary
    total_invoiced = sum(t['debit'] for t in transactions)
    total_paid = sum(t['credit'] for t in transactions)
    current_balance = customer.current_balance

    context = {
        'customer': customer,
        'transactions': transactions,
        'total_invoiced': total_invoiced,
        'total_paid': total_paid,
        'current_balance': current_balance,
        'form': form,
        'start_date': start_date,
        'end_date': end_date,
    }

    return render(request, 'accounting/customer_statement.html', context)
