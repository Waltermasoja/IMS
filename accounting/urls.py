from django.urls import path
from . import views

app_name = 'accounting'

urlpatterns = [
    # Dashboard
    path('', views.accounting_dashboard, name='dashboard'),
    
    # Cashbook
    path('cashbook/', views.cashbook_list, name='cashbook_list'),
    path('cashbook/add/', views.cashbook_add, name='cashbook_add'),
    path('cashflow/', views.cashflow_report, name='cashflow_report'),
    
    # Bank Reconciliation
    path('reconciliation/', views.bank_reconciliation_list, name='bank_reconciliation_list'),
    path('reconciliation/add/', views.bank_reconciliation_add, name='bank_reconciliation_add'),
    
    # Accounts Receivable
    path('invoices/', views.ar_invoice_list, name='ar_invoice_list'),
    path('invoices/<int:invoice_id>/', views.ar_invoice_detail, name='ar_invoice_detail'),
    path('payments/add/', views.ar_payment_add, name='ar_payment_add'),
    path('payments/add/<int:invoice_id>/', views.ar_payment_add, name='ar_payment_add_for_invoice'),
    
    # Layby
    path('layby/', views.layby_list, name='layby_list'),
    path('layby/<int:plan_id>/', views.layby_detail, name='layby_detail'),
    path('layby/<int:plan_id>/payment/', views.layby_payment_add, name='layby_payment_add'),
]