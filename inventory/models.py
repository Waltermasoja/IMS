from django.db import models

class inventory(models.Model):
    name = models.CharField(max_length=250,null=False,blank=False)
    cost = models.DecimalField(max_digits=19,decimal_places=2,blank=False)
    quantity_in_Stock = models.IntegerField(blank=False,null=False)
    quantity_sold =models.IntegerField(blank=False,null=False)
    sales = models.DecimalField(max_digits=19,decimal_places=2,blank=False)
    stock_date = models.DateField(auto_now_add=True)
    last_sale_date = models.DateField(auto_now=True)
    description = models.TextField(default='stock Item')

    def __str__(self) -> str:
        return self.name
