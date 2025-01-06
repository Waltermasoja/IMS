from django.db import models
from django.utils import timezone

class Inventory(models.Model):
    bought_from = models.CharField(max_length=100)
    name = models.CharField(max_length=100)
    purchase_price = models.DecimalField(max_digits=10, decimal_places=2)
    selling_price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity_in_Stock = models.IntegerField()
    description = models.TextField(blank=True)
    label = models.CharField(max_length=50)
    size = models.CharField(max_length=20)
    on_sale = models.BooleanField(default=True)
    created_date = models.DateTimeField(auto_now_add=True)
    last_updated = models.DateTimeField(auto_now=True)
    last_sale_date = models.DateTimeField(null=True, blank=True)

    @property
    def total_sales(self):
        return self.sales_set.aggregate(total=models.Sum('total_amount'))['total'] or 0

    @property
    def total_quantity_sold(self):
        return self.sales_set.aggregate(total=models.Sum('quantity_sold'))['total'] or 0

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = 'Inventory Item'
        verbose_name_plural = 'Inventory'

class Sales(models.Model):
    inventory_item = models.ForeignKey('Inventory', on_delete=models.CASCADE, related_name='sales_records')
    quantity_sold = models.IntegerField()
    sale_price = models.DecimalField(max_digits=10, decimal_places=2)
    sale_date = models.DateTimeField(default=timezone.now)
    discount_applied = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)

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
    inventory_item = models.ForeignKey(Inventory,on_delete=models.CASCADE)
    quantity_returned = models.IntegerField(blank=False,null=False)
    return_date = models.DateField(auto_now_add=True)
    reason = models.TextField()
    size = models.PositiveIntegerField(default=0,blank=False,null=False)
    label = models.TextField(max_length=255,default="")

    def __str__(self) -> str:
        return f'Return of {self.quantity_returned }{self.inventory_item.name}'
    def save(self, *args, **kwargs):
        self.size = self.inventory_item.size 
        super(Return, self).save(*args, **kwargs)

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

