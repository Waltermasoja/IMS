from django.db import models
from django.utils import timezone

class Inventory(models.Model):
    name = models.CharField(max_length=100)
    cost = models.DecimalField(max_digits=10, decimal_places=2)
    quantity_in_Stock = models.IntegerField()
    quantity_sold = models.IntegerField()
    sales = models.DecimalField(max_digits=10, decimal_places=2)
    last_sale_date = models.DateTimeField(default=timezone.now, null=True, blank=True)
    description = models.TextField(blank=True)
    label = models.CharField(max_length=50)
    size = models.CharField(max_length=20)
    cummulative_quantity_sold = models.IntegerField(default=0)
    cumulative_sales = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    sell = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    def __str__(self):
        return self.name

class Return(models.Model):
    inventory_item = models.ForeignKey(Inventory, on_delete=models.CASCADE)
    quantity_returned = models.IntegerField()
    return_date = models.DateTimeField(default=timezone.now)
    reason = models.TextField()

    def __str__(self):
        return f"{self.quantity_returned} {self.inventory_item.name}(s) returned"

class Damaged(models.Model):
    inventory_item = models.ForeignKey(Inventory, on_delete=models.CASCADE)
    quantity_damaged = models.IntegerField()
    damage_description = models.TextField()
    return_date = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.quantity_damaged} {self.inventory_item.name}(s) damaged"

class StockMovement(models.Model):
    MOVEMENT_CHOICES = [
        ('in', 'Stock In'),
        ('out', 'Stock Out')
    ]
    
    inventory_item = models.ForeignKey(Inventory, on_delete=models.CASCADE)
    movement_type = models.CharField(
        max_length=20, 
        choices=MOVEMENT_CHOICES,
        default='in'
    )
    quantity = models.IntegerField(default=0)
    stock_date = models.DateTimeField(default=timezone.now)
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"{self.movement_type}: {self.quantity} {self.inventory_item.name}(s)"

