from django.db import models
from django.utils import timezone
from django.db.models import Sum
from decimal import Decimal
from datetime import timedelta
import calendar
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

class UserProfile(models.Model):
    """Extended user profile for role-based access"""
    USER_ROLES = [
        ('admin', 'Administrator'),
        ('manager', 'Manager'),
        ('sales', 'Sales Associate'),
        ('viewer', 'Viewer Only'),
    ]
    
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(max_length=20, choices=USER_ROLES, default='sales')
    
    # POS Settings
    can_make_sales = models.BooleanField(default=True)
    can_process_returns = models.BooleanField(default=True)
    can_apply_discounts = models.BooleanField(default=True)
    max_discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=10.00,
                                              help_text="Maximum discount % this user can apply")
    
    # Access Control
    can_view_reports = models.BooleanField(default=False)
    can_manage_inventory = models.BooleanField(default=False)
    can_manage_suppliers = models.BooleanField(default=False)
    can_manage_users = models.BooleanField(default=False)
    
    # Metadata
    created_date = models.DateTimeField(auto_now_add=True)
    last_updated = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.user.username} - {self.get_role_display()}"
    
    @property
    def is_admin(self):
        return self.role == 'admin' or self.user.is_superuser
    
    @property
    def is_sales_person(self):
        return self.role == 'sales'
    
    @property
    def can_access_pos(self):
        return self.can_make_sales and self.role in ['admin', 'manager', 'sales']

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    """Auto-create UserProfile when User is created"""
    if created:
        # Default role based on staff status
        role = 'admin' if instance.is_staff else 'sales'
        UserProfile.objects.create(
            user=instance,
            role=role,
            can_view_reports=instance.is_staff,
            can_manage_inventory=instance.is_staff,
            can_manage_suppliers=instance.is_staff,
            can_manage_users=instance.is_superuser
        )

@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    """Save UserProfile when User is saved"""
    if hasattr(instance, 'profile'):
        instance.profile.save()
    else:
        # Create profile if it doesn't exist
        role = 'admin' if instance.is_staff else 'sales'
        UserProfile.objects.create(
            user=instance,
            role=role,
            can_view_reports=instance.is_staff,
            can_manage_inventory=instance.is_staff,
            can_manage_suppliers=instance.is_staff,
            can_manage_users=instance.is_superuser
        )

class Inventory(models.Model):
    bought_from = models.CharField(max_length=100)
    name = models.CharField(max_length=100)
    product_code = models.CharField(max_length=20, unique=True, blank=True, help_text="Unique product code for quick lookup")
    purchase_price = models.DecimalField(max_digits=10, decimal_places=2)
    selling_price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity_in_Stock = models.IntegerField()
    description = models.TextField(blank=True)
    label = models.CharField(max_length=50)
    size = models.CharField(max_length=20)
    weight = models.DecimalField(max_digits=8, decimal_places=2, default=0, help_text="Weight in kg")
    on_sale = models.BooleanField(default=True)
    category = models.ForeignKey('Inventory_category', on_delete=models.SET_NULL, null=True, blank=True)
    source_import_order = models.ForeignKey('ImportOrder', on_delete=models.SET_NULL, null=True, blank=True,
                                           related_name='created_products',
                                           help_text="Import order this product was first added from")
    created_date = models.DateTimeField(auto_now_add=True)
    last_updated = models.DateTimeField(auto_now=True)
    last_sale_date = models.DateTimeField(null=True, blank=True)
    sales_record = models.ManyToManyField('Sales', related_name='inventory_items', blank=True)

    @property
    def total_sales(self):
        return self.sales_records.aggregate(total=models.Sum('total_amount'))['total'] or 0

    @property
    def total_quantity_sold(self):
        return self.sales_records.aggregate(total=models.Sum('quantity_sold'))['total'] or 0

    def generate_product_code(self):
        """Auto-generate product code based on category and sequence"""
        if self.category:
            prefix = self.category.name[:3].upper()
        else:
            prefix = "GEN"  # General category
        
        # Find the last product with same prefix
        last_item = Inventory.objects.filter(
            product_code__startswith=prefix
        ).order_by('-product_code').first()
        
        if last_item and last_item.product_code:
            try:
                last_num = int(last_item.product_code.split('-')[-1])
                new_num = last_num + 1
            except (ValueError, IndexError):
                new_num = 1
        else:
            new_num = 1
        
        return f"{prefix}-{new_num:04d}"
    
    def save(self, *args, **kwargs):
        # Auto-generate product code if not provided
        if not self.product_code:
            self.product_code = self.generate_product_code()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = 'Inventory Item'
        verbose_name_plural = 'Inventory'

class Inventory_category(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    default_markup = models.DecimalField(max_digits=5, decimal_places=2, default=40, help_text="Default markup percentage for this category")
    date_created = models.DateTimeField(auto_now_add=True)
    date_updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

class Sales(models.Model):
    PAYMENT_METHODS = [
        ('CASH', 'Cash'),
        ('CREDIT', 'Credit'),
        ('LAYBY', 'Layby'),
    ]
    inventory_item = models.ForeignKey('Inventory', on_delete=models.CASCADE, related_name='sales_records')
    quantity_sold = models.IntegerField()
    sale_price = models.DecimalField(max_digits=10, decimal_places=2)
    sale_date = models.DateTimeField(default=timezone.now)
    discount_applied = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    receipt_number = models.CharField(max_length=20, blank=True, null=True)
    quantity_returned = models.IntegerField(default=0)
    payment_method = models.CharField(max_length=10, choices=PAYMENT_METHODS, default='CASH')
    recorded_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='sales_made')
    customer = models.ForeignKey('Customer', on_delete=models.SET_NULL, null=True, blank=True, related_name='sales')

    @property
    def can_be_returned(self):
        return self.quantity_sold > self.quantity_returned

    @property
    def remaining_quantity(self):
        return self.quantity_sold - self.quantity_returned

    def save(self, *args, **kwargs):
        if not self.total_amount:
            discounted_price = self.sale_price * (1 - self.discount_applied / 100)
            self.total_amount = discounted_price * self.quantity_sold
        super().save(*args, **kwargs)

    class Meta:
        ordering = ['-sale_date']
        verbose_name = 'Sale'
        verbose_name_plural = 'Sales'

    def __str__(self):
        return f"Sale of {self.quantity_sold} {self.inventory_item.name}(s) on {self.sale_date.date()}"

class Return(models.Model):
    inventory_item = models.ForeignKey(Inventory, on_delete=models.CASCADE)
    quantity_returned = models.IntegerField(blank=False, null=False)
    return_date = models.DateField(auto_now_add=True)
    reason = models.TextField()
    receipt_number = models.CharField(max_length=20, blank=True, null=True)
    sale = models.ForeignKey('Sales', on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self) -> str:
        return f'Return of {self.quantity_returned} {self.inventory_item.name}'

class Damaged(models.Model):
    inventory_item = models.ForeignKey('Inventory', on_delete=models.CASCADE)
    quantity_damaged = models.PositiveIntegerField()
    damage_description = models.TextField()
   
  

    def __str__(self):
        return f"{self.inventory_item.name} - {self.quantity_damaged} damaged"
from django.db import models

class StockMovement(models.Model):
    inventory_item = models.ForeignKey(Inventory, on_delete=models.CASCADE)
    movement_type = models.CharField(max_length=3, choices=[('IN', 'In'), ('OUT', 'Out')])
    quantity = models.IntegerField(blank=True,null=True)
    reason = models.CharField(max_length=200,blank=True,null=True)
    stock_date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.movement_type} - {self.quantity} units of {self.inventory_item.name}"

    class Meta:
        ordering = ['-stock_date']

class missing_inventory(models.Model):
    inventory_item = models.ForeignKey(Inventory, on_delete=models.CASCADE)
    quantity_missing = models.IntegerField()
    missing_date = models.DateTimeField(auto_now_add=True)
    reason = models.TextField()

    def __str__(self):
        return f"Missing {self.quantity_missing} of {self.inventory_item.name}"

# ==================== IMPORT ORDER & LANDED COST SYSTEM ====================

class Supplier(models.Model):
    """Supplier/vendor management for import orders"""
    name = models.CharField(max_length=200)
    country = models.CharField(max_length=100)
    contact_person = models.CharField(max_length=100, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=50, blank=True)
    
    # Financial
    payment_terms = models.CharField(max_length=100, default="NET 30")
    currency_preference = models.CharField(max_length=3, default='USD', choices=[
        ('USD', 'US Dollar'),
        ('TRY', 'Turkish Lira'),
        ('RMB', 'Renminbi'),
        ('ZAR', 'South African Rand'),
        ('GBP', 'British Pound'),
        ('CNY', 'Chinese Yuan'),
        ('EUR', 'Euro')
    ])
    
    # Address
    address = models.TextField(blank=True)
    
    # Stats (auto-calculated)
    total_orders = models.IntegerField(default=0)
    total_spent = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    
    # Status
    is_active = models.BooleanField(default=True)
    
    created_date = models.DateTimeField(auto_now_add=True)
    last_updated = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['name']
    
    def __str__(self):
        return f"{self.name} ({self.country})"
    
    @property
    def outstanding_balance(self):
        """Total unpaid invoices"""
        return self.import_orders.aggregate(
            total=Sum('invoices__outstanding_amount')
        )['total'] or 0

class ImportOrder(models.Model):
    """Main import order tracking with landed cost calculation"""
    
    STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('CONFIRMED', 'Confirmed'),
        ('SHIPPED', 'Shipped'),
        ('IN_TRANSIT', 'In Transit'),
        ('CUSTOMS', 'Customs Clearance'),
        ('RECEIVED', 'Received'),
        ('COMPLETED', 'Completed'),
        ('CANCELLED', 'Cancelled')
    ]
    
    ALLOCATION_METHODS = [
        ('VALUE', 'By Value (Recommended)'),
        ('QUANTITY', 'By Quantity'),
        ('WEIGHT', 'By Weight'),
        ('SMART', 'Smart Allocation'),
        ('CUSTOM', 'Custom')
    ]
    
    # Basic Info
    order_number = models.CharField(max_length=50, unique=True, editable=False)
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name='import_orders')
    reference_number = models.CharField(max_length=100, blank=True, help_text="Supplier's order reference")
    
    # Dates
    order_date = models.DateField(default=timezone.now)
    expected_arrival = models.DateField()
    actual_arrival = models.DateField(null=True, blank=True)
    
    # Currency
    currency = models.CharField(max_length=3, default='USD', choices=[
        ('USD', 'US Dollar'),
        ('ZAR', 'South African Rand'),
        ('GBP', 'British Pound'),
        ('CNY', 'Chinese Yuan'),
        ('EUR', 'Euro')
    ])
    exchange_rate = models.DecimalField(max_digits=10, decimal_places=4, help_text="Rate to local currency")
    
    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT')
    
    # Costs
    goods_cost = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    
    # Allocation
    allocation_method = models.CharField(max_length=20, choices=ALLOCATION_METHODS, default='SMART')
    allocation_completed = models.BooleanField(default=False)
    allocation_date = models.DateTimeField(null=True, blank=True)
    
    # Metadata
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True)
    created_date = models.DateTimeField(auto_now_add=True)
    last_updated = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-order_date']
    
    def save(self, *args, **kwargs):
        if not self.order_number:
            # Auto-generate order number: IO-2025-001
            last_order = ImportOrder.objects.filter(
                order_date__year=self.order_date.year
            ).order_by('-order_number').first()
            
            if last_order and last_order.order_number:
                try:
                    last_num = int(last_order.order_number.split('-')[-1])
                    new_num = last_num + 1
                except (ValueError, IndexError):
                    new_num = 1
            else:
                new_num = 1
            
            self.order_number = f"IO-{self.order_date.year}-{new_num:04d}"
        
        super().save(*args, **kwargs)
    
    @property
    def total_expenses(self):
        return self.expenses.aggregate(total=Sum('amount_in_local'))['total'] or 0
    
    @property
    def total_landed_cost(self):
        return self.goods_cost + self.total_expenses
    
    @property
    def total_items_count(self):
        return self.items.aggregate(total=Sum('quantity'))['total'] or 0
    
    @property
    def payment_status(self):
        """Overall payment status"""
        invoices = self.invoices.all()
        if not invoices:
            return 'NO_INVOICE'
        
        total_invoice = sum(inv.total_amount for inv in invoices)
        total_paid = sum(inv.amount_paid for inv in invoices)
        
        if total_paid >= total_invoice:
            return 'PAID'
        elif total_paid > 0:
            return 'PARTIAL'
        else:
            return 'UNPAID'
    
    def receive_all_goods(self):
        """Receive all items in this import order and update stock"""
        from .utils import run_allocation
        
        # Run allocation first if not done
        if not self.allocation_completed:
            run_allocation(self)
        
        # Receive each item
        items_received = 0
        for item in self.items.all():
            if not item.is_received:
                item.receive_goods()
                items_received += 1
        
        # Update order status
        self.status = 'RECEIVED'
        self.actual_arrival = timezone.now().date()
        self.save()
        
        return items_received
    
    def __str__(self):
        return f"{self.order_number} - {self.supplier.name}"

class SupplierInvoice(models.Model):
    """Track supplier invoices with payment status"""
    
    INVOICE_STATUS = [
        ('PENDING', 'Pending'),
        ('PARTIAL', 'Partially Paid'),
        ('PAID', 'Paid'),
        ('OVERDUE', 'Overdue'),
        ('CANCELLED', 'Cancelled')
    ]
    
    # References
    import_order = models.ForeignKey(ImportOrder, on_delete=models.CASCADE, related_name='invoices')
    invoice_number = models.CharField(max_length=100, unique=True)
    
    # Amounts
    currency = models.CharField(max_length=3, default='USD')
    total_amount = models.DecimalField(max_digits=15, decimal_places=2)
    amount_paid = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    
    # Dates
    invoice_date = models.DateField()
    due_date = models.DateField()
    
    # Status
    status = models.CharField(max_length=20, choices=INVOICE_STATUS, default='PENDING')
    
    # Documents
    invoice_file = models.FileField(upload_to='invoices/', null=True, blank=True)
    
    # Metadata
    notes = models.TextField(blank=True)
    created_date = models.DateTimeField(auto_now_add=True)
    last_updated = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-invoice_date']
    
    @property
    def outstanding_amount(self):
        return self.total_amount - self.amount_paid
    
    @property
    def is_overdue(self):
        return self.due_date < timezone.now().date() and self.outstanding_amount > 0
    
    @property
    def days_overdue(self):
        if self.is_overdue:
            return (timezone.now().date() - self.due_date).days
        return 0
    
    def update_status(self):
        """Auto-update status based on payments"""
        if self.amount_paid >= self.total_amount:
            self.status = 'PAID'
        elif self.amount_paid > 0:
            self.status = 'PARTIAL'
        elif self.is_overdue:
            self.status = 'OVERDUE'
        else:
            self.status = 'PENDING'
        self.save()
    
    def __str__(self):
        return f"Invoice {self.invoice_number} - {self.import_order.supplier.name}"

class InvoicePayment(models.Model):
    """Track individual payments against invoices"""
    
    PAYMENT_METHODS = [
        ('BANK_TRANSFER', 'Bank Transfer'),
        ('WIRE', 'Wire Transfer'),
        ('CASH', 'Cash'),
        ('CHECK', 'Check'),
        ('CREDIT_CARD', 'Credit Card'),
        ('MOBILE_MONEY', 'Mobile Money'),
        ('OTHER', 'Other')
    ]
    
    invoice = models.ForeignKey(SupplierInvoice, on_delete=models.CASCADE, related_name='payments')
    
    # Payment details
    payment_date = models.DateField(default=timezone.now)
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS)
    
    # Reference
    reference_number = models.CharField(max_length=100, blank=True)
    
    # Bank details (if applicable)
    bank_name = models.CharField(max_length=100, blank=True)
    transaction_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    # Documents
    receipt_file = models.FileField(upload_to='payment_receipts/', null=True, blank=True)
    
    # Metadata
    notes = models.TextField(blank=True)
    recorded_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True)
    created_date = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-payment_date']
    
    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        
        # Auto-update invoice amount paid
        total_paid = self.invoice.payments.aggregate(total=Sum('amount'))['total'] or 0
        self.invoice.amount_paid = total_paid
        self.invoice.update_status()
        
        # Create cashbook payment entry (supplier payment)
        try:
            CashbookEntry.objects.create(
                date=self.payment_date,
                reference=self.reference_number or self.invoice.invoice_number,
                description=f"Supplier payment - {self.invoice.import_order.supplier.name}",
                receipt_amount=0,
                payment_amount=self.amount,
                category='SUPPLIER',
                recorded_by=self.recorded_by,
            )
        except Exception:
            pass
    
    def __str__(self):
        return f"Payment of {self.amount} on {self.payment_date}"

class ImportExpense(models.Model):
    """Individual expenses for an import order"""
    
    EXPENSE_TYPES = [
        ('SHIPPING', 'Shipping/Freight'),
        ('CUSTOMS_DUTY', 'Customs Duty'),
        ('VAT', 'VAT/Tax'),
        ('CLEARING_AGENT', 'Clearing Agent Fee'),
        ('TRANSPORT', 'Local Transport'),
        ('INSURANCE', 'Insurance'),
        ('STORAGE', 'Storage/Warehousing'),
        ('BANK_CHARGES', 'Bank/Wire Charges'),
        ('HANDLING', 'Handling Fee'),
        ('INSPECTION', 'Inspection Fee'),
        ('OTHER', 'Other')
    ]
    
    import_order = models.ForeignKey(ImportOrder, on_delete=models.CASCADE, related_name='expenses')
    
    expense_type = models.CharField(max_length=50, choices=EXPENSE_TYPES)
    description = models.CharField(max_length=200)
    
    # Amount
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='USD')
    exchange_rate = models.DecimalField(max_digits=10, decimal_places=4, default=1)
    amount_in_local = models.DecimalField(max_digits=10, decimal_places=2)
    
    # Reference
    receipt_number = models.CharField(max_length=50, blank=True)
    date_incurred = models.DateField(default=timezone.now)
    
    # Documents
    receipt_file = models.FileField(upload_to='expense_receipts/', null=True, blank=True)
    
    # Payment tracking
    paid = models.BooleanField(default=False)
    payment_date = models.DateField(null=True, blank=True)
    
    created_date = models.DateTimeField(auto_now_add=True)
    
    def save(self, *args, **kwargs):
        # Auto-calculate local amount if not provided
        if not self.amount_in_local:
            if self.currency == self.import_order.currency:
                self.exchange_rate = self.import_order.exchange_rate
            self.amount_in_local = self.amount * self.exchange_rate
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"{self.expense_type} - {self.amount} {self.currency}"

class ImportOrderItem(models.Model):
    """Links inventory items to import orders with cost allocation"""
    
    import_order = models.ForeignKey(ImportOrder, on_delete=models.CASCADE, related_name='items')
    
    # Can link to existing product OR create new one
    inventory_item = models.ForeignKey(Inventory, on_delete=models.CASCADE, related_name='import_history', 
                                      null=True, blank=True)
    
    # Fields for creating NEW products (used if inventory_item is None)
    is_new_product = models.BooleanField(default=False, help_text="Check if this is a new product to be created")
    product_name = models.CharField(max_length=200, blank=True)
    product_category = models.ForeignKey('Inventory_category', on_delete=models.SET_NULL, null=True, blank=True,
                                        related_name='import_items')
    product_description = models.TextField(blank=True)
    product_label = models.CharField(max_length=50, blank=True)
    product_size = models.CharField(max_length=20, blank=True)
    product_weight = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    
    # Order details
    quantity = models.IntegerField()
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2)
    allocated_expenses = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    # Received tracking
    quantity_received = models.IntegerField(default=0, help_text="Quantity actually received")
    is_received = models.BooleanField(default=False)
    received_date = models.DateField(null=True, blank=True)
    
    # Optional: specific markup for this item
    markup_percentage = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    
    created_date = models.DateTimeField(auto_now_add=True)
    
    @property
    def total_cost(self):
        return self.unit_cost * self.quantity
    
    @property
    def landed_cost_per_unit(self):
        """Final cost per item including allocated expenses"""
        if self.quantity > 0:
            return self.unit_cost + (self.allocated_expenses / self.quantity)
        return self.unit_cost
    
    @property
    def suggested_selling_price(self):
        """Auto-calculate selling price with markup"""
        if self.markup_percentage:
            markup = self.markup_percentage / 100
        else:
            # Use category default or system default
            if self.inventory_item and hasattr(self.inventory_item, 'category') and self.inventory_item.category:
                markup = self.inventory_item.category.default_markup / 100
            elif self.product_category:
                markup = self.product_category.default_markup / 100
            else:
                markup = Decimal('0.40')  # 40% default
        
        return self.landed_cost_per_unit * (1 + markup)
    
    def create_inventory_item(self):
        """Create inventory item from import order item if it's a new product"""
        if not self.is_new_product or self.inventory_item:
            return self.inventory_item
        
        if not self.product_name:
            raise ValueError("Product name is required to create new inventory item")
        
        # Create the inventory item
        inventory_item = Inventory.objects.create(
            name=self.product_name,
            category=self.product_category,
            description=self.product_description,
            label=self.product_label or self.product_name[:50],
            size=self.product_size or '0',
            weight=self.product_weight,
            purchase_price=self.landed_cost_per_unit,
            selling_price=self.suggested_selling_price,
            quantity_in_Stock=0,  # Will be updated when goods are received
            bought_from=self.import_order.supplier.name,
            on_sale=True,
            source_import_order=self.import_order
        )
        
        # Link back to this import order item
        self.inventory_item = inventory_item
        self.save()
        
        return inventory_item
    
    def receive_goods(self, quantity_received=None, update_stock=True):
        """Mark goods as received and optionally update stock"""
        if quantity_received is None:
            quantity_received = self.quantity
        
        self.quantity_received = quantity_received
        self.is_received = True
        self.received_date = timezone.now().date()
        
        # Create inventory item if it's a new product
        if self.is_new_product and not self.inventory_item:
            self.create_inventory_item()
        
        # Update stock if requested
        if update_stock and self.inventory_item:
            self.inventory_item.quantity_in_Stock += quantity_received
            
            # Update prices with landed cost
            self.inventory_item.purchase_price = self.landed_cost_per_unit
            self.inventory_item.selling_price = self.suggested_selling_price
            self.inventory_item.save()
            
            # Create stock movement
            StockMovement.objects.create(
                inventory_item=self.inventory_item,
                movement_type='IN',
                quantity=quantity_received,
                reason=f'Import Order {self.import_order.order_number} received'
            )
        
        self.save()
    
    def __str__(self):
        if self.inventory_item:
            return f"{self.quantity}x {self.inventory_item.name}"
        elif self.product_name:
            return f"{self.quantity}x {self.product_name} (New)"
        return f"Import Order Item #{self.id}"

# ==================== BASIC ACCOUNTING AND CUSTOMER CREDIT/LAYBY ====================

class Customer(models.Model):
    STATUS_CHOICES = [
        ('ACTIVE', 'Active'),
        ('SUSPENDED', 'Suspended'),
        ('INACTIVE', 'Inactive'),
    ]

    name = models.CharField(max_length=200)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=50, blank=True)
    address = models.TextField(blank=True)

    # Credit profile (for on-account sales)
    credit_limit = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    current_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0,
                                         help_text="Outstanding A/R balance")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='ACTIVE')
    
    # Loyalty and communication preferences
    opt_in_for_emails = models.BooleanField(default=False, help_text="Customer agreed to receive email invoices")
    purchase_count = models.IntegerField(default=0, help_text="Total number of purchases for loyalty tracking")

    created_date = models.DateTimeField(auto_now_add=True)
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name




# ==================== SALES INVOICES FOR CUSTOMER RECEIPTS ====================

class SalesInvoice(models.Model):
    """Customer-facing invoices for sales transactions"""
    
    invoice_number = models.CharField(max_length=50, unique=True, editable=False)
    invoice_date = models.DateTimeField(default=timezone.now)
    
    # Customer is optional for cash sales but required for credit/layby
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, null=True, blank=True, 
                                related_name='sales_invoices')
    
    # Totals
    subtotal = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=15, decimal_places=2)
    
    # Email tracking
    email_sent = models.BooleanField(default=False)
    email_sent_date = models.DateTimeField(null=True, blank=True)
    
    # Metadata
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, 
                                   related_name='invoices_created')
    created_date = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-invoice_date']
    
    def save(self, *args, **kwargs):
        if not self.invoice_number:
            # Auto-generate invoice number: INV-2025-0001
            year = self.invoice_date.year
            last_invoice = SalesInvoice.objects.filter(
                invoice_date__year=year
            ).order_by('-invoice_number').first()
            
            if last_invoice and last_invoice.invoice_number:
                try:
                    last_num = int(last_invoice.invoice_number.split('-')[-1])
                    new_num = last_num + 1
                except (ValueError, IndexError):
                    new_num = 1
            else:
                new_num = 1
            
            self.invoice_number = f"INV-{year}-{new_num:04d}"
        
        super().save(*args, **kwargs)
    
    def send_email(self):
        """Send invoice to customer via email if they opted in"""
        if not self.customer or not self.customer.opt_in_for_emails or not self.customer.email:
            return False
        
        from django.template.loader import render_to_string
        from django.core.mail import send_mail
        from django.conf import settings
        
        try:
            # Render email template
            context = {'invoice': self, 'items': self.items.all()}
            html_message = render_to_string('inventory/invoice_email.html', context)
            
            send_mail(
                subject=f'Invoice {self.invoice_number}',
                message=f'Please find your invoice {self.invoice_number} attached.',
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[self.customer.email],
                html_message=html_message,
                fail_silently=False,
            )
            
            self.email_sent = True
            self.email_sent_date = timezone.now()
            self.save(update_fields=['email_sent', 'email_sent_date'])
            return True
        except Exception as e:
            print(f"Error sending email: {e}")
            return False
    
    def __str__(self):
        customer_name = self.customer.name if self.customer else "Walk-in Customer"
        return f"{self.invoice_number} - {customer_name}"


class SalesInvoiceItem(models.Model):
    """Line items for sales invoices"""
    
    invoice = models.ForeignKey(SalesInvoice, on_delete=models.CASCADE, related_name='items')
    sale = models.ForeignKey(Sales, on_delete=models.SET_NULL, null=True, blank=True)
    
    # Item details (stored for historical record)
    product_name = models.CharField(max_length=200)
    product_code = models.CharField(max_length=20, blank=True)
    quantity = models.IntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    line_total = models.DecimalField(max_digits=15, decimal_places=2)
    
    def save(self, *args, **kwargs):
        # Auto-calculate line total
        if not self.line_total:
            discounted_price = self.unit_price * (1 - self.discount_percent / 100)
            self.line_total = discounted_price * self.quantity
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"{self.quantity}x {self.product_name}"

