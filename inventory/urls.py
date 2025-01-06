from django.urls import path
from .views import *
from django.contrib.auth import views as auth_views

urlpatterns = [
    path('',inventory_list,name='inventory'),
    path('product/<int:pk>',per_product_view,name='per_product'),
    path('add_inventory/',add_product,name='add_inventory'),
    path('delete_inventory/<int:pk>/',delete_inventory,name='delete_inventory'),
    path('update_inventory/<int:pk>/',update_inventory,name='update_inventory'),
    path('dashboard/',dashboard,name='dashboard'),
    path('sales_summary/',sales_summary,name='sales_summary'),
    path('inventory/returns/<int:pk>',returnInventory,name='returnInventory'),
    path('inventory/returns',return_summary,name='return_summary'),
    path('inventory/damages/<int:pk>',damagedInventory,name='damagedInventory'),
    path('inventory/damages',obsolate_summary,name='obsolete_summary'),
    path('inventory/stock_movement_summary/<int:pk>/', stock_movement_summary, name='stock_movement_summary'),
    path('login/', auth_views.LoginView.as_view(), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('search/', search, name='search'),
    path('search', search_results, name='search_results'),
]