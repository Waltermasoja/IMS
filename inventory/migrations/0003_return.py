# Generated by Django 5.0.6 on 2024-08-09 05:30

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0002_inventory_description'),
    ]

    operations = [
        migrations.CreateModel(
            name='Return',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('quantity_returned', models.IntegerField()),
                ('return_date', models.DateField(auto_now_add=True)),
                ('reason', models.TextField()),
                ('inventory_item', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='inventory.inventory')),
            ],
        ),
    ]
