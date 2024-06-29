from django.urls import path
from .views import inventory_list,per_product_view,add_product,delete_inventory,update_inventory,dashboard

urlpatterns = [
    path('',inventory_list,name='inventory'),
    path('product/<int:pk>',per_product_view,name='per_product'),
    path('add_inventory/',add_product,name='add_inventory'),
    path('delete_inventory/<int:pk>/',delete_inventory,name='delete_inventory'),
    path('update_inventory/<int:pk>/',update_inventory,name='update_inventory'),
    path('dashboard/',dashboard,name='dashboard'),
]