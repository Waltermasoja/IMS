from django.db import models, transaction
from django.utils import timezone
from django.db.models import Sum, F, DecimalField, ExpressionWrapper
from decimal import Decimal
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from django.core.exceptions import ValidationError

# ==================== GENERAL LEDGER & JOURNAL ENTRIES ====================

class GLAccount(models.Model):
    TYPE_CHOICES = [
        ('ASSET', 'Asset'),
        ('LIAB', 'Liability'),
        ('EQUITY', 'Equity'),
        ('INCOME', 'Income'),
        ('EXP', 'Expense'),
        ('CONTRA_REV', 'Contra-Revenue'),  # For discounts, returns, allowances
    ]

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=200)
    type = models.CharField(max_length=15, choices=TYPE_CHOICES)
    is_active = models.BooleanField(default=True)

    @property
    def balance(self):
        """
        Calculate account balance from journal entries.
        For ASSET, EXPENSE, and CONTRA_REVENUE accounts: Debit increases, Credit decreases (Debit - Credit)
        For LIABILITY, EQUITY, and INCOME accounts: Credit increases, Debit decreases (Credit - Debit)
        """
        totals = JournalLine.objects.filter(account=self).aggregate(
            total_debits=Sum('debit'),
            total_credits=Sum('credit'),
        )
        total_debits = totals['total_debits'] or Decimal('0.00')
        total_credits = totals['total_credits'] or Decimal('0.00')

        # Normal debit balance accounts (Assets, Expenses, Contra-Revenue)
        if self.type in ['ASSET', 'EXP', 'CONTRA_REV']:
            return total_debits - total_credits
        # Normal credit balance accounts (Liabilities, Equity, Income)
        else:
            return total_credits - total_debits

    def __str__(self):
        return f"{self.code} - {self.name}"


class JournalEntry(models.Model):
    entry_date = models.DateTimeField(default=timezone.now)
    memo = models.CharField(max_length=255, blank=True)
    reference = models.CharField(max_length=100, blank=True)
    created_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True)
    posted_at = models.DateTimeField(auto_now_add=True)

    # NULL = corporate / inter-shop entry. Shop-scoped P&L filters on this.
    shop = models.ForeignKey(
        'inventory.Shop', on_delete=models.PROTECT, null=True, blank=True,
        related_name='journal_entries',
    )

    def __str__(self):
        return f"JE#{self.id} {self.entry_date.date()} - {self.memo}"

    @property
    def total_debits(self):
        return self.lines.aggregate(total=Sum('debit'))['total'] or Decimal('0.00')

    @property
    def total_credits(self):
        return self.lines.aggregate(total=Sum('credit'))['total'] or Decimal('0.00')

    @property
    def is_balanced(self):
        totals = self.lines.aggregate(d=Sum('debit'), c=Sum('credit'))
        return (totals['d'] or Decimal('0')) == (totals['c'] or Decimal('0'))

    def assert_balanced(self):
        """Raise ValidationError if debits != credits (call after all lines are saved)."""
        if not self.is_balanced:
            raise ValidationError(
                f'Journal entry is not balanced (debits {self.total_debits} != credits {self.total_credits}).'
            )


class JournalLine(models.Model):
    entry = models.ForeignKey(JournalEntry, on_delete=models.CASCADE, related_name='lines')
    account = models.ForeignKey(GLAccount, on_delete=models.PROTECT)
    description = models.CharField(max_length=200, blank=True)
    debit = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    credit = models.DecimalField(max_digits=15, decimal_places=2, default=0)

    # Optional references for traceability
    inventory_item = models.ForeignKey('inventory.Inventory', on_delete=models.SET_NULL, null=True, blank=True)
    sale = models.ForeignKey('inventory.Sales', on_delete=models.SET_NULL, null=True, blank=True)
    customer = models.ForeignKey('inventory.Customer', on_delete=models.SET_NULL, null=True, blank=True)

    def clean(self):
        if self.debit and self.credit:
            raise ValidationError('A line cannot have both debit and credit')
        if not self.debit and not self.credit:
            raise ValidationError('Either debit or credit must be provided')

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        side = 'Dr' if self.debit and self.debit > 0 else 'Cr'
        amount = self.debit or self.credit
        return f"{self.account.code} {side} {amount}"

# ==================== ACCOUNTS RECEIVABLE ====================

class ARInvoice(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PARTIAL', 'Partially Paid'),
        ('PAID', 'Paid'),
        ('OVERDUE', 'Overdue'),
        ('CANCELLED', 'Cancelled'),
    ]

    customer = models.ForeignKey('inventory.Customer', on_delete=models.PROTECT, related_name='invoices')
    invoice_number = models.CharField(max_length=50, unique=True)
    invoice_date = models.DateField(default=timezone.now, db_index=True)
    due_date = models.DateField(db_index=True)

    total_amount = models.DecimalField(max_digits=15, decimal_places=2)
    amount_paid = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING', db_index=True)

    # Optional linkage to a POS sale or ticket
    sale = models.ForeignKey('inventory.Sales', on_delete=models.SET_NULL, null=True, blank=True, related_name='ar_invoices')
    ticket = models.OneToOneField(
        'inventory.SalesTicket', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='ar_invoice',
    )

    shop = models.ForeignKey(
        'inventory.Shop', on_delete=models.PROTECT, null=True, blank=True,
        related_name='ar_invoices',
    )

    created_date = models.DateTimeField(auto_now_add=True)
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-invoice_date']

    @property
    def outstanding_amount(self):
        return (self.total_amount or Decimal('0')) - (self.amount_paid or Decimal('0'))

    @property
    def is_overdue(self):
        return self.outstanding_amount > 0 and self.due_date < timezone.now().date()

    def update_status(self):
        if self.amount_paid >= self.total_amount:
            self.status = 'PAID'
        elif self.amount_paid > 0:
            self.status = 'PARTIAL'
        elif self.is_overdue:
            self.status = 'OVERDUE'
        else:
            self.status = 'PENDING'
        self.save(update_fields=['status', 'last_updated'])

    def __str__(self):
        return f"AR {self.invoice_number} - {self.customer.name}"


class ARPayment(models.Model):
    PAYMENT_METHODS = [
        ('CASH', 'Cash'),
        ('BANK', 'Bank Transfer'),
        ('CARD', 'Card'),
        ('MOBILE', 'Mobile Money'),
        ('OTHER', 'Other'),
    ]

    invoice = models.ForeignKey(ARInvoice, on_delete=models.CASCADE, related_name='payments')
    payment_date = models.DateField(default=timezone.now)
    amount = models.DecimalField(max_digits=15, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    method = models.CharField(max_length=10, choices=PAYMENT_METHODS)
    reference = models.CharField(max_length=100, blank=True)
    recorded_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True)

    # Denormalized from invoice.shop for reporting / cashbook reconciliation.
    shop = models.ForeignKey(
        'inventory.Shop', on_delete=models.PROTECT, null=True, blank=True,
        related_name='ar_payments',
    )

    created_date = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        from accounting.utils import require_gl

        is_new = self.pk is None
        if self.invoice_id and not self.shop_id:
            self.shop = self.invoice.shop
        with transaction.atomic():
            super().save(*args, **kwargs)

            # If this is an AR invoice for a layby plan, also update the layby plan's amount_paid
            if hasattr(self.invoice, 'layby_plan') and self.invoice.layby_plan:
                ar_payments_total = self.invoice.payments.aggregate(total=Sum('amount'))['total'] or 0
                layby_payments_total = self.invoice.layby_plan.payments.aggregate(total=Sum('amount'))['total'] or 0
                combined_total = ar_payments_total + layby_payments_total

                self.invoice.amount_paid = combined_total
                self.invoice.layby_plan.amount_paid = combined_total
                self.invoice.layby_plan.save(update_fields=['amount_paid'])
            else:
                total_paid = self.invoice.payments.aggregate(total=Sum('amount'))['total'] or 0
                self.invoice.amount_paid = total_paid

            self.invoice.save(update_fields=['amount_paid'])
            self.invoice.update_status()

            if not is_new:
                return

            cash = require_gl('1000')
            ar = require_gl('1200')
            je = JournalEntry.objects.create(
                memo=f"AR payment {self.reference}", shop=self.shop,
            )
            JournalLine.objects.create(entry=je, account=cash, debit=self.amount, description='AR payment')
            JournalLine.objects.create(
                entry=je, account=ar, credit=self.amount,
                description=self.invoice.invoice_number, customer=self.invoice.customer
            )
            je.assert_balanced()
            self.invoice.customer.current_balance = (self.invoice.customer.current_balance or Decimal('0')) - self.amount
            self.invoice.customer.save(update_fields=['current_balance'])
            CashbookEntry.objects.create(
                date=self.payment_date,
                reference=self.reference or self.invoice.invoice_number,
                description=f"A/R payment - {self.invoice.customer.name}",
                receipt_amount=self.amount,
                payment_amount=0,
                category='AR',
                recorded_by=self.recorded_by,
                shop=self.shop,
            )

    def __str__(self):
        return f"Payment {self.amount} on {self.invoice.invoice_number}"

# ==================== LAYBY SYSTEM ====================

class LaybyPlan(models.Model):
    STATUS_CHOICES = [
        ('ACTIVE', 'Active'),
        ('FULFILLED', 'Fulfilled'),
        ('CANCELLED', 'Cancelled'),
        ('DEFAULTED', 'Defaulted'),
    ]

    customer = models.ForeignKey('inventory.Customer', on_delete=models.PROTECT, related_name='layby_plans')
    created_date = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ACTIVE')
    deposit_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    due_date = models.DateField(null=True, blank=True)
    schedule = models.JSONField(null=True, blank=True, help_text="Installment schedule and metadata")

    # Link to AR Invoice for proper receivables tracking
    ar_invoice = models.OneToOneField('ARInvoice', on_delete=models.SET_NULL, null=True, blank=True,
                                      related_name='layby_plan')
    ticket = models.OneToOneField(
        'inventory.SalesTicket', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='layby_plan',
    )

    shop = models.ForeignKey(
        'inventory.Shop', on_delete=models.PROTECT, null=True, blank=True,
        related_name='layby_plans',
    )

    def recompute_totals(self):
        line_expr = ExpressionWrapper(
            F('unit_price') * F('quantity'),
            output_field=DecimalField(max_digits=15, decimal_places=2),
        )
        total = self.items.aggregate(total=Sum(line_expr))['total'] or Decimal('0')
        self.total_price = total
        paid = self.payments.aggregate(total=Sum('amount'))['total'] or Decimal('0')
        self.amount_paid = paid
        self.save(update_fields=['total_price', 'amount_paid', 'last_updated']) if hasattr(self, 'last_updated') else self.save()

    @property
    def remaining(self):
        return (self.total_price or Decimal('0')) - (self.amount_paid or Decimal('0'))

    def __str__(self):
        return f"Layby #{self.id} - {self.customer.name}"


class LaybyItem(models.Model):
    plan = models.ForeignKey(LaybyPlan, on_delete=models.CASCADE, related_name='items')
    inventory_item = models.ForeignKey('inventory.Inventory', on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)

    @property
    def line_total(self):
        return (self.unit_price or Decimal('0')) * (self.quantity or 0)

    def __str__(self):
        return f"{self.quantity} x {self.inventory_item.name}"


class LaybyPayment(models.Model):
    plan = models.ForeignKey(LaybyPlan, on_delete=models.CASCADE, related_name='payments')
    payment_date = models.DateField(default=timezone.now)
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    reference = models.CharField(max_length=100, blank=True)
    recorded_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True)

    # Denormalized from plan.shop for reporting.
    shop = models.ForeignKey(
        'inventory.Shop', on_delete=models.PROTECT, null=True, blank=True,
        related_name='layby_payments',
    )

    created_date = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        from accounting.utils import create_layby_ar_invoice, require_gl

        is_new = self.pk is None
        if self.plan_id and not self.shop_id:
            self.shop = self.plan.shop
        print(f"[LAYBY][MODEL] Saving LaybyPayment: plan={getattr(self.plan,'id',None)}, amount={self.amount}, reference={self.reference}")
        with transaction.atomic():
            super().save(*args, **kwargs)
            print(f"[LAYBY][MODEL] Saved payment id={self.id}")

            if not is_new:
                return

            if not self.plan.ar_invoice:
                create_layby_ar_invoice(self.plan)

            layby_payments_total = self.plan.payments.aggregate(total=Sum('amount'))['total'] or 0
            ar_payments_total = 0
            if self.plan.ar_invoice:
                ar_payments_total = self.plan.ar_invoice.payments.aggregate(total=Sum('amount'))['total'] or 0

            combined_total = layby_payments_total + ar_payments_total
            print(f"[LAYBY][MODEL] Layby payments: ${layby_payments_total}, AR payments: ${ar_payments_total}, Combined: ${combined_total}")

            self.plan.amount_paid = combined_total
            if self.plan.ar_invoice:
                self.plan.ar_invoice.amount_paid = combined_total
                self.plan.ar_invoice.save(update_fields=['amount_paid'])
                self.plan.ar_invoice.update_status()

            if self.plan.amount_paid >= self.plan.total_price and self.plan.status == 'ACTIVE':
                self.plan.status = 'FULFILLED'
            self.plan.save()
            print(f"[LAYBY][MODEL] Plan status={self.plan.status}, amount_paid={self.plan.amount_paid}, total_price={self.plan.total_price}")

            cash = require_gl('1000')
            ar = require_gl('1200')
            je = JournalEntry.objects.create(
                memo=f"Layby payment - Plan #{self.plan_id}", shop=self.shop,
            )
            JournalLine.objects.create(entry=je, account=cash, debit=self.amount, description='Layby payment received')
            JournalLine.objects.create(
                entry=je, account=ar, credit=self.amount,
                description=f'Layby payment - {self.plan.ar_invoice.invoice_number}', customer=self.plan.customer
            )
            print(f"[LAYBY][MODEL] Journal posted for payment: JE#{je.id}")
            je.assert_balanced()

            self.plan.customer.current_balance = (self.plan.customer.current_balance or Decimal('0')) - self.amount
            self.plan.customer.save(update_fields=['current_balance'])

            CashbookEntry.objects.create(
                date=self.payment_date,
                reference=self.reference or f"LAYBY-{self.plan_id}",
                description=f"Layby payment - {self.plan.customer.name}",
                receipt_amount=self.amount,
                payment_amount=0,
                category='LAYBY',
                recorded_by=self.recorded_by,
                shop=self.shop,
            )
            print("[LAYBY][MODEL] Cashbook receipt created")

    def __str__(self):
        return f"Layby payment {self.amount} for plan #{self.plan_id}"

# ==================== CASHBOOK & CASHFLOW ====================

class CashbookEntry(models.Model):
    """Daily cash transactions ledger"""
    date = models.DateField(default=timezone.now, db_index=True)
    reference = models.CharField(max_length=100, blank=True)
    description = models.CharField(max_length=255, blank=True)
    category = models.CharField(max_length=50, blank=True)
    receipt_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    payment_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    recorded_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True)
    shop = models.ForeignKey(
        'inventory.Shop', on_delete=models.PROTECT, null=True, blank=True,
        related_name='cashbook_entries',
    )
    created_date = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['date', 'id']

    @property
    def net_amount(self):
        return (self.receipt_amount or Decimal('0')) - (self.payment_amount or Decimal('0'))

    def __str__(self):
        return f"{self.date} {self.reference} {self.net_amount}"

class BankReconciliation(models.Model):
    month = models.DateField(help_text="Use first day of month")
    opening_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    closing_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    bank_statement_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    difference = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    reconciled = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    created_date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Bank Reconciliation {self.month.strftime('%Y-%m')}"

# ==================== OPERATING EXPENSES ====================

class Expense(models.Model):
    CATEGORY_CHOICES = [
        ('RENT', 'Rent'),
        ('UTILITIES', 'Utilities'),
        ('WAGES', 'Wages'),
        ('FREIGHT', 'Freight'),
        ('MARKETING', 'Marketing'),
        ('OTHER', 'Other'),
    ]
    PAYMENT_METHODS = [
        ('CASH', 'Cash'),
        ('BANK', 'Bank Transfer'),
        ('CARD', 'Card'),
        ('MOBILE', 'Mobile Money'),
        ('OTHER', 'Other'),
    ]

    date = models.DateField(default=timezone.now)
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES)
    description = models.CharField(max_length=255, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    vat_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0'),
        help_text='Input VAT recoverable (portion of amount). 0 for exempt/non-VATable expenses.',
    )
    gl_account = models.ForeignKey(GLAccount, on_delete=models.PROTECT, limit_choices_to={'type': 'EXP'})
    payment_method = models.CharField(max_length=10, choices=PAYMENT_METHODS, default='CASH')
    reference = models.CharField(max_length=100, blank=True)
    recorded_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True)
    # NULL = corporate expense (accounting fees, directors, software). Non-NULL
    # shops roll into that shop's P&L only.
    shop = models.ForeignKey(
        'inventory.Shop', on_delete=models.PROTECT, null=True, blank=True,
        related_name='expenses',
    )
    created_date = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        from accounting.utils import get_expense_payment_credit_account

        is_new = self.pk is None
        with transaction.atomic():
            super().save(*args, **kwargs)
            if not is_new:
                return
            credit_acct = get_expense_payment_credit_account(self.payment_method)
            je = JournalEntry.objects.create(
                memo=f"Expense: {self.category}", reference=self.reference,
                created_by=self.recorded_by, shop=self.shop,
            )
            JournalLine.objects.create(entry=je, account=self.gl_account, debit=self.amount, description=self.description)
            JournalLine.objects.create(
                entry=je, account=credit_acct, credit=self.amount,
                description='Cash/bank payment',
            )
            je.assert_balanced()
            CashbookEntry.objects.create(
                date=self.date,
                reference=self.reference or f"EXP-{self.id}",
                description=self.description or self.category,
                category='EXPENSE',
                receipt_amount=0,
                payment_amount=self.amount,
                recorded_by=self.recorded_by,
                shop=self.shop,
            )
