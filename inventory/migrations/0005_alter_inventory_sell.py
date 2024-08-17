# Generated by Django 5.0.6 on 2024-08-09 07:18

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0004_inventory_sell'),
    ]

    operations = [
        migrations.AlterField(
            model_name='inventory',
            name='sell',
            field=models.DecimalField(blank=True, decimal_places=2, default=0.0, max_digits=19),
        ),
    ]