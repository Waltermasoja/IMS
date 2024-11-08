from django.db import models

class Inventory(models.Model):
    name = models.CharField(max_length=250,null=False,blank=False)
    cost = models.DecimalField(max_digits=19,decimal_places=2,blank=False)
    quantity_in_Stock = models.IntegerField(blank=False,null=False)
    quantity_sold =models.IntegerField(blank=False,null=False)
    sales = models.DecimalField(max_digits=19,decimal_places=2,blank=False)
    stock_date = models.DateField(auto_now_add=True)
    last_sale_date = models.DateField(auto_now=True)
    description = models.TextField(default='stock Item')
    sell = models.DecimalField(max_digits=19,blank=True,decimal_places=2,default=0.00)
    cummulative_quantity_sold = models.IntegerField(default=0)
    cumulative_sales = models.DecimalField(max_digits=19, decimal_places=2, default=0.00)
    def __str__(self) -> str:
        return self.name

    
class Return(models.Model):
    inventory_item = models.ForeignKey(Inventory,on_delete=models.CASCADE)
    quantity_returned = models.IntegerField(blank=False,null=False)
    return_date = models.DateField(auto_now_add=True)
    reason = models.TextField()

    def __str__(self) -> str:
        return f'Return of {self.quantity_returned }{self.inventory_item.name}'


class Damaged(models.Model):
    inventory_item = models.ForeignKey('Inventory', on_delete=models.CASCADE)
    quantity_damaged = models.PositiveIntegerField()
    damage_description = models.TextField()
   
  

    def __str__(self):
        return f"{self.inventory_item.name} - {self.quantity_damaged} damaged"

class Sales(models.Model):
    inventory_item = models.ForeignKey(Inventory, on_delete=models.CASCADE, related_name='sale_items')
    quantity_sold = models.PositiveIntegerField()
    sale_date = models.DateTimeField(auto_now_add=True)
    sale_description = models.TextField(blank=True)
    discount_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)

    @property
    def unit_price(self):
        return self.inventory_item.price

    @property
    def discounted_price(self):
        return self.unit_price * (1 - self.discount_percentage / 100)

    @property
    def total_price(self):
        return self.quantity_sold * self.discounted_price

    def __str__(self):
        return f"{self.inventory_item.name} - {self.quantity_sold} sold on {self.sale_date}"

