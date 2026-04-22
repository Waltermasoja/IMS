from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.db import transaction
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.db.models import Sum, Q
from django.db.models.functions import TruncMonth
from django.core.paginator import Paginator
from django.core.exceptions import ValidationError
from decimal import Decimal
import calendar

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
            
            # Dr Unearned Revenue by amount_paid (what was actually deposited & posted)
            # Cr Sales Revenue by total_price (full sale value)
            # If amount_paid < total_price, any shortfall is an outstanding balance
            # already tracked via AR; we only release what was received.
            recognize_amount = plan.amount_paid
            total_price = plan.total_price or Decimal('0')
            JournalLine.objects.create(
                entry=je,
                account=unearned,
                debit=recognize_amount,
                description='Recognize revenue from layby'
            )
            JournalLine.objects.create(
                entry=je,
                account=revenue,
                credit=recognize_amount,
                description='Sales revenue recognized',
                customer=plan.customer
            )

            total_cogs = Decimal('0')
            for item in plan.items.select_related('inventory_item'):
                cogs_amount = (item.inventory_item.purchase_price or Decimal('0')) * (item.quantity or 0)
                total_cogs += cogs_amount
            if total_price > 0 and recognize_amount < total_price:
                total_cogs = (total_cogs * recognize_amount / total_price).quantize(Decimal('0.01'))

            if total_cogs > 0:
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
            je.assert_balanced()
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
    from accounting.utils import MissingGLAccountError, require_gl

    plan = get_object_or_404(LaybyPlan, pk=plan_id)
    from inventory.models import StockMovement
    fee = Decimal(request.POST.get('cancellation_fee', '0') or '0')

    try:
        with transaction.atomic():
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
                JournalLine.objects.create(
                    entry=je, account=unearned, debit=unpaid,
                    description='Release unpaid commitment (clear AR)',
                )
                JournalLine.objects.create(
                    entry=je, account=ar, credit=unpaid,
                    description='Clear layby receivable', customer=plan.customer,
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
    except (MissingGLAccountError, ValidationError) as exc:
        messages.error(request, str(exc))
        return redirect('accounting:layby_detail', plan_id=plan.id)

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
        before = CashbookEntry.objects.filter(date__lt=start_date).aggregate(
            r=Sum('receipt_amount'), p=Sum('payment_amount')
        )
        opening = Decimal(str(before['r'] or 0)) - Decimal(str(before['p'] or 0))

    totals = qs.aggregate(r=Sum('receipt_amount'), p=Sum('payment_amount'))
    receipts = totals['r'] or 0
    payments = totals['p'] or 0
    closing = opening + receipts - payments

    # Build running balance rows (over full filtered set, then paginate)
    running = opening
    all_rows = []
    for e in qs:
        running += (e.receipt_amount or 0) - (e.payment_amount or 0)
        all_rows.append({'entry': e, 'running': running})

    paginator = Paginator(all_rows, 50)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'accounting/cashbook_list.html', {
        'form': form,
        'rows': page_obj,
        'page_obj': page_obj,
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
    total_in = 0
    total_out = 0
    total_net = 0

    for m in monthly:
        r = float(m['receipts'] or 0)
        p = float(m['payments'] or 0)
        n = r - p
        rows.append({
            'month': m['month'],
            'receipts': r,
            'payments': p,
            'net': n,
        })
        total_in += r
        total_out += p
        total_net += n

    return render(request, 'accounting/cashflow_report.html', {
        'rows': rows,
        'total_in': total_in,
        'total_out': total_out,
        'total_net': total_net,
    })

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
    qs = ARInvoice.objects.all().select_related('customer').order_by('-invoice_date')
    paginator = Paginator(qs, 50)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'accounting/ar_invoice_list.html', {
        'invoices': page_obj,
        'page_obj': page_obj,
    })

@login_required
def ar_invoice_detail(request, invoice_id):
    """A/R invoice detail with payment history"""
    from datetime import date
    invoice = get_object_or_404(ARInvoice, pk=invoice_id)

    # Get payment history - for layby invoices, show layby payments; for regular invoices, show AR payments
    if hasattr(invoice, 'layby_plan') and invoice.layby_plan:
        # For layby invoices, show layby payments
        layby_payments = invoice.layby_plan.payments.all().order_by('-payment_date')
        ar_payments = invoice.payments.all().order_by('-payment_date')
        # Combine both types
        all_payments = list(layby_payments) + list(ar_payments)
        all_payments.sort(key=lambda x: x.payment_date, reverse=True)
        payments = all_payments
    else:
        # For regular credit sale invoices, show AR payments
        payments = invoice.payments.all().order_by('-payment_date')

    return render(request, 'accounting/ar_invoice_detail.html', {
        'invoice': invoice,
        'payments': payments,
        'today': date.today().isoformat(),
    })

@login_required
def ar_payment_add(request, invoice_id=None):
    """Add payment to A/R invoice - supports pre-selection from invoice or customer"""
    from inventory.models import Customer

    invoice = None
    customer = None
    customer_invoices = []

    # Get customer_id from query params for customer-specific payment
    customer_id = request.GET.get('customer_id')

    if invoice_id:
        invoice = get_object_or_404(ARInvoice, pk=invoice_id)
        customer = invoice.customer
        # Get all outstanding invoices for this customer
        customer_invoices = ARInvoice.objects.filter(
            customer=customer,
            status__in=['PENDING', 'PARTIAL', 'OVERDUE']
        ).select_related('customer').order_by('-invoice_date')
    elif customer_id:
        customer = get_object_or_404(Customer, pk=customer_id)
        # Get all outstanding invoices for this customer
        customer_invoices = ARInvoice.objects.filter(
            customer=customer,
            status__in=['PENDING', 'PARTIAL', 'OVERDUE']
        ).select_related('customer').order_by('-invoice_date')

    if request.method == 'POST':
        form = ARPaymentFormSimple(request.POST)
        if form.is_valid():
            payment = form.save(commit=False)
            payment.recorded_by = request.user
            payment.save()
            messages.success(request, f'Payment of ${payment.amount} recorded for invoice {payment.invoice.invoice_number}')
            return redirect('accounting:ar_invoice_detail', invoice_id=payment.invoice.id)
    else:
        initial = {}
        if invoice:
            initial['invoice'] = invoice
            initial['amount'] = invoice.outstanding_amount
        form = ARPaymentFormSimple(initial=initial)

        # If customer is specified, limit invoice choices
        if customer:
            form.fields['invoice'].queryset = customer_invoices

    return render(request, 'accounting/ar_payment_form.html', {
        'form': form,
        'invoice': invoice,
        'customer': customer,
        'customer_invoices': customer_invoices,
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
    qs = Expense.objects.all().order_by('-date', '-id')
    paginator = Paginator(qs, 50)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'accounting/expense_list.html', {
        'expenses': page_obj,
        'page_obj': page_obj,
    })

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
    ap_outstanding = SupplierInvoice.objects.filter(
        status__in=['PENDING', 'PARTIAL', 'OVERDUE']
    ).aggregate(
        total=Sum(F('total_amount') - F('amount_paid'))
    )['total'] or Decimal('0')

    # === INVENTORY VALUE ===
    # Use physical inventory calculation (quantity * purchase_price)
    # GL Account 1300 may not reflect accurate inventory value if receiving
    # transactions haven't been posted to the GL
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

    # === AP ALERTS ===
    today = timezone.now().date()

    # Overdue supplier invoices
    overdue_ap_invoices = SupplierInvoice.objects.filter(
        status__in=['PENDING', 'PARTIAL'],
        due_date__lt=today
    ).select_related('import_order__supplier').order_by('due_date')[:5]

    overdue_ap_count = SupplierInvoice.objects.filter(
        status__in=['PENDING', 'PARTIAL'],
        due_date__lt=today
    ).count()

    overdue_ap_total = SupplierInvoice.objects.filter(
        status__in=['PENDING', 'PARTIAL'],
        due_date__lt=today
    ).aggregate(
        total=Sum(F('total_amount') - F('amount_paid'))
    )['total'] or Decimal('0')

    # Invoices due within 7 days
    due_soon_date = today + timedelta(days=7)
    due_soon_ap = SupplierInvoice.objects.filter(
        status__in=['PENDING', 'PARTIAL'],
        due_date__gte=today,
        due_date__lte=due_soon_date
    ).count()

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
        # AP Alerts
        'overdue_ap_invoices': overdue_ap_invoices,
        'overdue_ap_count': overdue_ap_count,
        'overdue_ap_total': overdue_ap_total,
        'due_soon_ap': due_soon_ap,
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

    now = timezone.now()
    if month_str and year_str:
        try:
            month = int(month_str)
            year = int(year_str)
            if not (1 <= month <= 12) or not (2000 <= year <= 2100):
                raise ValueError
        except (ValueError, TypeError):
            month = now.month
            year = now.year
    else:
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
    # Get gross sales from GL account 4000 (credits to revenue)
    try:
        revenue_account = GLAccount.objects.get(code='4000')
        gross_sales = JournalLine.objects.filter(
            entry__entry_date__range=(start_date, end_date),
            account=revenue_account,
            credit__gt=0
        ).aggregate(total=Sum('credit'))['total'] or Decimal('0')
    except GLAccount.DoesNotExist:
        gross_sales = Decimal('0')

    # Get sales discounts from GL account 4100 (debits to contra-revenue)
    try:
        discount_account = GLAccount.objects.get(code='4100')
        sales_discounts = JournalLine.objects.filter(
            entry__entry_date__range=(start_date, end_date),
            account=discount_account,
            debit__gt=0
        ).aggregate(total=Sum('debit'))['total'] or Decimal('0')
    except GLAccount.DoesNotExist:
        sales_discounts = Decimal('0')

    # Net sales = Gross sales - Discounts
    sales_revenue = gross_sales - sales_discounts

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

    # Calculate expense ratios for visualization
    cogs_ratio = round((cogs / total_revenue * 100) if total_revenue > 0 else 0, 1)
    expense_ratio = round((total_expenses / total_revenue * 100) if total_revenue > 0 else 0, 1)

    context = {
        'month': month,
        'year': year,
        'month_name': calendar.month_name[month],
        'months': months,
        'years': years,

        # Revenue
        'gross_sales': gross_sales,
        'sales_discounts': sales_discounts,
        'sales_revenue': sales_revenue,  # Net sales (gross - discounts)
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

        # Ratios for visualization
        'cogs_ratio': cogs_ratio,
        'expense_ratio': expense_ratio,

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
    from django.db.models import F

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
    # Use GL Account 2000 balance for consistency with double-entry bookkeeping
    # GL is credited when goods received, debited when payment made
    # The balance property returns Credit - Debit for liability accounts (positive = owe money)
    try:
        ap_account = GLAccount.objects.get(code='2000')
        accounts_payable = ap_account.balance
    except GLAccount.DoesNotExist:
        # Fallback to SupplierInvoice calculation if GL account doesn't exist
        from inventory.models import SupplierInvoice
        accounts_payable = SupplierInvoice.objects.filter(
            status__in=['PENDING', 'PARTIAL', 'OVERDUE']
        ).aggregate(
            total=Sum(F('total_amount') - F('amount_paid'))
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

    # Calculate financial ratios
    debt_ratio = round((total_liabilities / total_assets * 100) if total_assets > 0 else 0, 1)
    equity_ratio = round((owners_equity / total_assets * 100) if total_assets > 0 else 0, 1)

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
        'debt_ratio': debt_ratio,
        'equity_ratio': equity_ratio,
    }

    return render(request, 'accounting/balance_sheet.html', context)


@login_required
def accounts_payable_list(request):
    """Simple Accounts Payable list - what we owe suppliers."""
    from inventory.models import SupplierInvoice, Supplier

    # Get all unpaid or partially paid invoices
    unpaid_invoices = SupplierInvoice.objects.filter(
        status__in=['PENDING', 'PARTIAL', 'OVERDUE']
    ).select_related('import_order__supplier').order_by('due_date')

    # Calculate totals
    total_outstanding = Decimal('0')
    overdue_amount = Decimal('0')
    today = timezone.now().date()

    supplier_summary = {}

    for invoice in unpaid_invoices:
        amount_due = invoice.total_amount - invoice.amount_paid

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
def ap_aging_report(request):
    """Accounts Payable Aging Report - shows outstanding invoices by age brackets."""
    from inventory.models import SupplierInvoice, Supplier
    from datetime import date

    # Get all outstanding supplier invoices
    invoices = SupplierInvoice.objects.exclude(
        status__in=['PAID', 'CANCELLED']
    ).select_related('import_order__supplier').order_by('due_date')

    # Filter by supplier if specified
    supplier_id = request.GET.get('supplier')
    if supplier_id:
        invoices = invoices.filter(import_order__supplier_id=supplier_id)

    # Age brackets (based on due date, not invoice date)
    today = date.today()
    aging_data = []

    for invoice in invoices:
        outstanding = invoice.outstanding_amount
        if outstanding <= 0:
            continue

        # Calculate days overdue (negative means not yet due)
        if invoice.due_date:
            days_overdue = (today - invoice.due_date).days
        else:
            days_overdue = (today - invoice.invoice_date).days  # Fallback to invoice date

        # Determine age bracket (based on overdue days)
        if days_overdue <= 0:
            bracket = 'Current'
        elif days_overdue <= 30:
            bracket = '1-30'
        elif days_overdue <= 60:
            bracket = '31-60'
        elif days_overdue <= 90:
            bracket = '61-90'
        else:
            bracket = '90+'

        supplier_name = invoice.import_order.supplier.name if invoice.import_order and invoice.import_order.supplier else 'Unknown'

        aging_data.append({
            'invoice': invoice,
            'supplier_name': supplier_name,
            'days_overdue': max(0, days_overdue),
            'outstanding': outstanding,
            'bracket': bracket,
            'is_overdue': days_overdue > 0,
        })

    # Calculate bracket totals
    brackets = {
        'Current': Decimal('0'),
        '1-30': Decimal('0'),
        '31-60': Decimal('0'),
        '61-90': Decimal('0'),
        '90+': Decimal('0'),
    }

    for data in aging_data:
        brackets[data['bracket']] += data['outstanding']

    total_outstanding = sum(brackets.values())
    total_overdue = total_outstanding - brackets['Current']

    # Calculate percentages
    bracket_percentages = {}
    for bracket, amount in brackets.items():
        if total_outstanding > 0:
            bracket_percentages[bracket] = round(amount / total_outstanding * 100, 1)
        else:
            bracket_percentages[bracket] = 0

    # Create template-friendly list
    brackets_list = [
        {'label': 'Current', 'amount': brackets['Current'], 'percentage': bracket_percentages['Current'], 'color': 'success'},
        {'label': '1-30 Days', 'amount': brackets['1-30'], 'percentage': bracket_percentages['1-30'], 'color': 'info'},
        {'label': '31-60 Days', 'amount': brackets['31-60'], 'percentage': bracket_percentages['31-60'], 'color': 'warning'},
        {'label': '61-90 Days', 'amount': brackets['61-90'], 'percentage': bracket_percentages['61-90'], 'color': 'orange'},
        {'label': '90+ Days', 'amount': brackets['90+'], 'percentage': bracket_percentages['90+'], 'color': 'danger'},
    ]

    # Supplier summary for aging
    supplier_aging = {}
    for data in aging_data:
        supplier = data['supplier_name']
        if supplier not in supplier_aging:
            supplier_aging[supplier] = {
                'Current': Decimal('0'),
                '1-30': Decimal('0'),
                '31-60': Decimal('0'),
                '61-90': Decimal('0'),
                '90+': Decimal('0'),
                'total': Decimal('0'),
            }
        supplier_aging[supplier][data['bracket']] += data['outstanding']
        supplier_aging[supplier]['total'] += data['outstanding']

    # Convert to sorted list
    supplier_aging_list = [
        {'name': name, **amounts}
        for name, amounts in supplier_aging.items()
    ]
    supplier_aging_list.sort(key=lambda x: x['total'], reverse=True)

    # Get suppliers for filter dropdown
    suppliers = Supplier.objects.filter(is_active=True).order_by('name')

    context = {
        'aging_data': aging_data,
        'brackets_list': brackets_list,
        'supplier_aging': supplier_aging_list,
        'total_outstanding': total_outstanding,
        'total_overdue': total_overdue,
        'suppliers': suppliers,
        'selected_supplier': supplier_id or '',
        'today': today,
    }

    return render(request, 'accounting/ap_aging_report.html', context)


@login_required
def supplier_invoice_detail(request, invoice_id):
    """View details of a supplier invoice with payment history."""
    from inventory.models import SupplierInvoice, InvoicePayment

    invoice = get_object_or_404(
        SupplierInvoice.objects.select_related('import_order__supplier'),
        pk=invoice_id
    )

    # Get payment history
    payments = invoice.payments.all().order_by('-payment_date')

    # Calculate payment timeline
    payment_timeline = []
    running_balance = invoice.total_amount

    # Add invoice creation
    payment_timeline.append({
        'date': invoice.invoice_date,
        'type': 'Invoice',
        'description': f'Invoice {invoice.invoice_number} received',
        'amount': invoice.total_amount,
        'balance': running_balance,
    })

    # Add each payment
    for payment in payments.order_by('payment_date'):
        running_balance -= payment.amount
        payment_timeline.append({
            'date': payment.payment_date,
            'type': 'Payment',
            'description': f'{payment.get_payment_method_display()} - {payment.reference_number or "No ref"}',
            'amount': payment.amount,
            'balance': running_balance,
        })

    context = {
        'invoice': invoice,
        'payments': payments,
        'payment_timeline': payment_timeline,
        'supplier': invoice.import_order.supplier if invoice.import_order else None,
        'import_order': invoice.import_order,
    }

    return render(request, 'accounting/supplier_invoice_detail.html', context)


@login_required
def customer_statement(request, customer_id):
    """Customer account statement - shows transaction history and balance."""
    from inventory.models import Customer
    from accounting.models import LaybyPlan, LaybyPayment

    customer = get_object_or_404(Customer, pk=customer_id)

    # Date range filter
    form = DateRangeForm(request.GET or None)
    start_date = end_date = None

    if form.is_valid():
        start_date = form.cleaned_data.get('start_date')
        end_date = form.cleaned_data.get('end_date')

    # Get all transactions for this customer
    transactions = []

    # AR Invoices (debits - customer owes us) - includes both credit sales and layby plans
    invoices = ARInvoice.objects.filter(customer=customer)
    if start_date:
        invoices = invoices.filter(invoice_date__gte=start_date)
    if end_date:
        invoices = invoices.filter(invoice_date__lte=end_date)

    for invoice in invoices:
        # Check if this is a layby invoice
        is_layby = hasattr(invoice, 'layby_plan') and invoice.layby_plan is not None

        if is_layby:
            description = f'Layby plan #{invoice.layby_plan.id} - {invoice.invoice_number}'
            invoice_type = 'Layby Plan'
        else:
            description = f'Credit sale - Invoice {invoice.invoice_number}'
            invoice_type = 'Credit Invoice'

        transactions.append({
            'date': invoice.invoice_date,
            'type': invoice_type,
            'reference': invoice.invoice_number,
            'description': description,
            'debit': invoice.total_amount,
            'credit': Decimal('0'),
            'related_object': invoice,
        })

    # AR Payments (credits - customer paid us on credit invoices)
    payments = ARPayment.objects.filter(invoice__customer=customer)
    if start_date:
        payments = payments.filter(payment_date__gte=start_date)
    if end_date:
        payments = payments.filter(payment_date__lte=end_date)

    for payment in payments:
        transactions.append({
            'date': payment.payment_date,
            'type': 'Credit Payment',
            'reference': payment.reference or f'Payment #{payment.id}',
            'description': f'Payment on {payment.invoice.invoice_number} - {payment.get_method_display()}',
            'debit': Decimal('0'),
            'credit': payment.amount,
            'related_object': payment,
        })

    # Layby Payments (credits - customer paid us on layby plans)
    layby_payments = LaybyPayment.objects.filter(plan__customer=customer)
    if start_date:
        layby_payments = layby_payments.filter(payment_date__gte=start_date)
    if end_date:
        layby_payments = layby_payments.filter(payment_date__lte=end_date)

    for lp in layby_payments:
        invoice_ref = lp.plan.ar_invoice.invoice_number if lp.plan.ar_invoice else f'Plan #{lp.plan.id}'
        transactions.append({
            'date': lp.payment_date,
            'type': 'Layby Payment',
            'reference': lp.reference or f'LAYBY-{lp.plan.id}',
            'description': f'Layby deposit on {invoice_ref}',
            'debit': Decimal('0'),
            'credit': lp.amount,
            'related_object': lp,
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

    # Calculate available credit
    available_credit = Decimal('0')
    if customer.credit_limit > 0:
        available_credit = max(Decimal('0'), customer.credit_limit - current_balance)

    context = {
        'customer': customer,
        'transactions': transactions,
        'total_invoiced': total_invoiced,
        'total_paid': total_paid,
        'current_balance': current_balance,
        'available_credit': available_credit,
        'form': form,
        'start_date': start_date,
        'end_date': end_date,
    }

    return render(request, 'accounting/customer_statement.html', context)


@login_required
def outstanding_receivables_summary(request):
    """Summary dashboard of all outstanding receivables - credit sales and layby plans."""
    from inventory.models import Customer

    # Get all outstanding AR invoices
    outstanding_invoices = ARInvoice.objects.filter(
        status__in=['PENDING', 'PARTIAL', 'OVERDUE']
    ).select_related('customer').order_by('-invoice_date')

    # Separate credit sales from layby plans
    credit_invoices = []
    layby_invoices = []

    for invoice in outstanding_invoices:
        if hasattr(invoice, 'layby_plan') and invoice.layby_plan:
            layby_invoices.append(invoice)
        else:
            credit_invoices.append(invoice)

    # Calculate totals
    total_credit_outstanding = sum(inv.outstanding_amount for inv in credit_invoices)
    total_layby_outstanding = sum(inv.outstanding_amount for inv in layby_invoices)
    total_outstanding = total_credit_outstanding + total_layby_outstanding

    # Get customers with outstanding balances
    customers_with_balance = Customer.objects.filter(
        current_balance__gt=0
    ).order_by('-current_balance')

    # Overdue invoices
    overdue_invoices = [inv for inv in outstanding_invoices if inv.is_overdue]
    total_overdue = sum(inv.outstanding_amount for inv in overdue_invoices)

    context = {
        'total_outstanding': total_outstanding,
        'total_credit_outstanding': total_credit_outstanding,
        'total_layby_outstanding': total_layby_outstanding,
        'total_overdue': total_overdue,
        'credit_invoice_count': len(credit_invoices),
        'layby_invoice_count': len(layby_invoices),
        'overdue_count': len(overdue_invoices),
        'credit_invoices': credit_invoices[:10],  # Top 10
        'layby_invoices': layby_invoices[:10],  # Top 10
        'customers_with_balance': customers_with_balance[:10],  # Top 10
        'overdue_invoices': overdue_invoices[:10],  # Top 10
    }

    return render(request, 'accounting/outstanding_receivables.html', context)


@login_required
def manage_gl_accounts(request):
    """
    Manage General Ledger accounts - user-friendly interface to view and manage GL accounts
    without needing Django admin access.
    """
    # Group accounts by type
    accounts_by_type = {}
    for account_type, type_label in GLAccount.TYPE_CHOICES:
        accounts = GLAccount.objects.filter(type=account_type, is_active=True).order_by('code')
        if accounts.exists():
            accounts_by_type[account_type] = {
                'label': type_label,
                'accounts': accounts,
                'count': accounts.count()
            }

    # Calculate totals for balance sheet items
    asset_balance = sum(acc.balance for acc in GLAccount.objects.filter(type='ASSET', is_active=True))
    liability_balance = sum(acc.balance for acc in GLAccount.objects.filter(type='LIAB', is_active=True))
    equity_balance = sum(acc.balance for acc in GLAccount.objects.filter(type='EQUITY', is_active=True))

    context = {
        'accounts_by_type': accounts_by_type,
        'total_accounts': GLAccount.objects.filter(is_active=True).count(),
        'asset_balance': asset_balance,
        'liability_balance': liability_balance,
        'equity_balance': equity_balance,
    }

    return render(request, 'accounting/manage_gl_accounts.html', context)


# ──────────────────────────────────────────────────────────────────────────────
# C2 — VAT return: output VAT − input VAT per period, per shop
# ──────────────────────────────────────────────────────────────────────────────

@login_required
def vat_report(request):
    """VAT return summary: output VAT (from sales) − input VAT (from expenses, imports)."""
    from inventory.models import SalesTicket, SalesLine, Shop, ImportExpense
    from .models import Expense
    from datetime import date as date_cls
    from datetime import timedelta

    today = timezone.localdate()
    default_start = today.replace(day=1)
    start_str = request.GET.get('start_date', default_start.isoformat())
    end_str = request.GET.get('end_date', today.isoformat())
    shop_id = request.GET.get('shop_id') or None

    try:
        start_date = date_cls.fromisoformat(start_str)
        end_date = date_cls.fromisoformat(end_str)
    except ValueError:
        start_date, end_date = default_start, today

    shop_filter = None
    if shop_id:
        shop_filter = Shop.objects.filter(pk=shop_id).first()

    # Output VAT — from non-voided SalesTicket within period
    tickets_qs = SalesTicket.objects.filter(
        created_at__date__gte=start_date,
        created_at__date__lte=end_date,
        voided=False,
    )
    if shop_filter:
        tickets_qs = tickets_qs.filter(shop=shop_filter)

    output_agg = tickets_qs.aggregate(
        taxable_excl=Sum('subtotal_excl_vat'),
        output_vat=Sum('vat_total'),
        gross=Sum('total_incl_vat'),
    )
    output_vat = output_agg['output_vat'] or Decimal('0')
    taxable_excl = output_agg['taxable_excl'] or Decimal('0')
    gross_sales = output_agg['gross'] or Decimal('0')

    # Per-tender breakdown for context
    tender_rows = []
    for tender, label in [('IMMEDIATE', 'Immediate'), ('CREDIT', 'Credit'), ('LAYBY', 'Layby')]:
        tagg = tickets_qs.filter(terms=tender).aggregate(
            t=Sum('total_incl_vat'), v=Sum('vat_total'),
        )
        tender_rows.append({
            'label': label,
            'total': tagg['t'] or Decimal('0'),
            'vat': tagg['v'] or Decimal('0'),
        })

    # Zero-rated / exempt sales (line-level aggregation)
    line_qs = SalesLine.objects.filter(
        ticket__in=tickets_qs,
    )
    exempt_sales = line_qs.filter(is_vat_exempt=True).aggregate(
        t=Sum('line_total_incl_vat')
    )['t'] or Decimal('0')

    # Input VAT — from Expense.vat_amount
    expenses_qs = Expense.objects.filter(date__gte=start_date, date__lte=end_date)
    if shop_filter:
        expenses_qs = expenses_qs.filter(Q(shop=shop_filter) | Q(shop__isnull=True))
    input_vat_exp = expenses_qs.aggregate(v=Sum('vat_amount'))['v'] or Decimal('0')

    # Input VAT from ImportExpense rows tagged as VAT
    import_vat_qs = ImportExpense.objects.filter(
        import_order__order_date__gte=start_date,
        import_order__order_date__lte=end_date,
        expense_type='VAT',
    )
    input_vat_imports = import_vat_qs.aggregate(a=Sum('amount'))['a'] or Decimal('0')

    total_input_vat = input_vat_exp + input_vat_imports
    net_vat_due = output_vat - total_input_vat

    context = {
        'start_date': start_date,
        'end_date': end_date,
        'shops': Shop.objects.filter(is_active=True).order_by('name'),
        'selected_shop': shop_filter,
        'output_vat': output_vat,
        'taxable_excl_vat': taxable_excl,
        'gross_sales': gross_sales,
        'exempt_sales': exempt_sales,
        'tender_rows': tender_rows,
        'input_vat_expenses': input_vat_exp,
        'input_vat_imports': input_vat_imports,
        'total_input_vat': total_input_vat,
        'net_vat_due': net_vat_due,
        'expenses': expenses_qs.select_related('gl_account', 'shop').order_by('date'),
        'ticket_count': tickets_qs.count(),
    }
    return render(request, 'accounting/vat_report.html', context)


@login_required
def vat_report_export_csv(request):
    """CSV export for the VAT report."""
    import csv
    from inventory.models import SalesTicket
    from datetime import date as date_cls

    start_str = request.GET.get('start_date')
    end_str = request.GET.get('end_date')
    shop_id = request.GET.get('shop_id') or None
    today = timezone.localdate()
    try:
        start_date = date_cls.fromisoformat(start_str) if start_str else today.replace(day=1)
        end_date = date_cls.fromisoformat(end_str) if end_str else today
    except ValueError:
        start_date, end_date = today.replace(day=1), today

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="vat_report_{start_date}_{end_date}.csv"'
    w = csv.writer(response)
    w.writerow(['Receipt', 'Shop', 'Date', 'Terms', 'Subtotal_Excl_VAT', 'VAT', 'Total_Incl_VAT'])

    qs = SalesTicket.objects.filter(
        created_at__date__gte=start_date,
        created_at__date__lte=end_date,
        voided=False,
    ).select_related('shop')
    if shop_id:
        qs = qs.filter(shop_id=shop_id)

    for t in qs.order_by('created_at'):
        w.writerow([
            t.receipt_number, t.shop.code, t.created_at.date(), t.terms,
            t.subtotal_excl_vat, t.vat_total, t.total_incl_vat,
        ])
    return response
