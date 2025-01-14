from django.urls import path
from .views import *
from django.contrib.auth import views as auth_views

urlpatterns = [
    path('',inventory_list,name='inventory'),
    path('product/<int:pk>',per_product_view,name='per_product'),
    path('add_inventory/',add_product,name='add_inventory'),
    path('delete_inventory/<int:pk>/',delete_inventory,name='delete_inventory'),
    path('make_sale/<int:pk>/',make_sale,name='make_sale'),
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
    path('inventory_category/', inventory_category, name='inventory_category'),
    path('add_inventory_category/', add_inventory_category, name='add_inventory_category'),
    path('delete_inventory_category/<int:pk>/', delete_inventory_category, name='delete_inventory_category'),
    path('update_inventory_category/<int:pk>/', update_inventory_category, name='update_inventory_category'),
    path('add-category-ajax/', add_category_ajax, name='add_category_ajax'),
    path('inventory_update/<int:pk>/', inventory_update, name='inventory_update'),
]