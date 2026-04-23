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
    path('layby/<int:plan_id>/fulfill/', views.layby_fulfill_action, name='layby_fulfill_action'),
    path('layby/<int:plan_id>/cancel/', views.layby_cancel_action, name='layby_cancel_action'),

    # Expenses
    path('expenses/', views.expense_list, name='expense_list'),
    path('expenses/add/', views.expense_add, name='expense_add'),

    # AR Reports
    path('reports/ar-aging/', views.ar_aging_report, name='ar_aging_report'),
    path('reports/credit-utilization/', views.customer_credit_utilization_report, name='customer_credit_utilization_report'),
    path('reports/credit-sales-summary/', views.credit_sales_summary_report, name='credit_sales_summary_report'),
    path('reports/outstanding-receivables/', views.outstanding_receivables_summary, name='outstanding_receivables_summary'),

    # AP Reports
    path('payables/', views.accounts_payable_list, name='accounts_payable_list'),
    path('reports/ap-aging/', views.ap_aging_report, name='ap_aging_report'),
    path('payables/invoice/<int:invoice_id>/', views.supplier_invoice_detail, name='supplier_invoice_detail'),

    # Simple Business Reports
    path('reports/daily-cash/', views.daily_cash_summary, name='daily_cash_summary'),
    path('reports/profit-loss/', views.profit_loss_report, name='profit_loss_report'),
    path('reports/balance-sheet/', views.balance_sheet, name='balance_sheet'),
    path('reports/customer-statement/<int:customer_id>/', views.customer_statement, name='customer_statement'),

    # Management Pages
    path('manage/gl-accounts/', views.manage_gl_accounts, name='manage_gl_accounts'),

    # VAT Return
    path('reports/vat/', views.vat_report, name='vat_report'),
    path('reports/vat/export/', views.vat_report_export_csv, name='vat_report_export_csv'),

    # EcoCash / Bank reconciliation (D2)
    path('reconciliation/ecocash/', views.ecocash_reconciliation, name='ecocash_reconciliation'),

    # Accountant exports (D3)
    path('exports/', views.accountant_exports_index, name='accountant_exports'),
    path('exports/gl-detail.xlsx', views.export_gl_detail_xlsx, name='export_gl_detail_xlsx'),
    path('exports/trial-balance.xlsx', views.export_trial_balance_xlsx, name='export_trial_balance_xlsx'),
    path('exports/sales-tickets.xlsx', views.export_sales_tickets_xlsx, name='export_sales_tickets_xlsx'),
]
