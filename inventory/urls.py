from django.urls import path
from .views import *
from .invoice_views import (
    invoice_list, invoice_detail, generate_invoice_from_sales,
    send_invoice_email, print_invoice, customer_invoices
)
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
    path('api/product-search/', product_search_ajax, name='product_search_ajax'),
    path('api/product-details/<int:pk>/', product_details_ajax, name='product_details_ajax'),
    path('invoice/print/<str:receipt_number>/', invoice_print, name='invoice_print'),
    path('inventory/update/<int:pk>/', update_inventory, name='update_inventory_ajax'),
    path('pos/', pos_interface, name='pos_interface'),
    # Customers & A/R & Layby
    path('customers/', customers_list, name='customers_list'),
    path('customers/new/', customer_create, name='customer_create'),
    path('customers/create-ajax/', customer_create_ajax, name='customer_create_ajax'),
    path('customers/<int:pk>/edit/', customer_update, name='customer_update'),
    

    # Suppliers
    path('suppliers/', suppliers_list, name='suppliers_list'),
    path('suppliers/new/', supplier_create, name='supplier_create'),
    path('suppliers/<int:pk>/edit/', supplier_update, name='supplier_update'),
    # Import Orders
    path('import-orders/', import_orders_list, name='import_orders_list'),
    path('import-orders/new/', import_order_create, name='import_order_create'),
    path('import-orders/<int:pk>/', import_order_detail, name='import_order_detail'),
    path('import-orders/<int:pk>/allocate/', import_order_allocate, name='import_order_allocate'),
    path('import-orders/<int:pk>/bulk-upload/', import_order_bulk_upload, name='import_order_bulk_upload'),
    path('import-orders/<int:pk>/receive-goods/', import_order_receive_goods, name='import_order_receive_goods'),
    path('import-orders/csv-template/', download_csv_template, name='download_csv_template'),
    # Invoices & Payments
    path('import-orders/<int:pk>/invoice/add/', add_supplier_invoice, name='add_supplier_invoice'),
    path('invoices/<int:pk>/payment/add/', add_invoice_payment, name='add_invoice_payment'),
    # Simple reports
    path('reports/sales-simple/', sales_report_simple, name='sales_report_simple'),
    path('reports/sales/', sales_report_detailed, name='sales_report_detailed'),
    path('reports/sales/export/', sales_report_export_csv, name='sales_report_export_csv'),

    path('invoices/', invoice_list, name='invoice_list'),
    path('invoices/<int:invoice_id>/', invoice_detail, name='invoice_detail'),
    path('invoices/generate/', generate_invoice_from_sales, name='generate_invoice'),
    path('invoices/<int:invoice_id>/send-email/', send_invoice_email, name='send_invoice_email'),
    path('invoices/<int:invoice_id>/print/', print_invoice, name='print_invoice'),
    path('customers/<int:customer_id>/invoices/', customer_invoices, name='customer_invoices'),
]
