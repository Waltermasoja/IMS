from django.contrib import admin
from .models import (
    GLAccount, JournalEntry, JournalLine, ARInvoice, ARPayment,
    LaybyPlan, LaybyItem, LaybyPayment, CashbookEntry, BankReconciliation, Expense
)

# ==================== GENERAL LEDGER ====================

@admin.register(GLAccount)
class GLAccountAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'type', 'is_active']
    list_filter = ['type', 'is_active']
    search_fields = ['code', 'name']

class JournalLineInline(admin.TabularInline):
    model = JournalLine
    extra = 0

@admin.register(JournalEntry)
class JournalEntryAdmin(admin.ModelAdmin):
    list_display = ['id', 'entry_date', 'memo', 'reference']
    inlines = [JournalLineInline]

# ==================== ACCOUNTS RECEIVABLE ====================

@admin.register(ARInvoice)
class ARInvoiceAdmin(admin.ModelAdmin):
    list_display = ['invoice_number', 'customer', 'total_amount', 'amount_paid', 'status', 'due_date']
    list_filter = ['status', 'invoice_date', 'due_date']
    search_fields = ['invoice_number', 'customer__name']
    readonly_fields = ['created_date', 'last_updated']

@admin.register(ARPayment)
class ARPaymentAdmin(admin.ModelAdmin):
    list_display = ['invoice', 'amount', 'method', 'payment_date', 'reference']
    list_filter = ['method', 'payment_date']
    search_fields = ['invoice__invoice_number', 'reference']

# ==================== LAYBY MANAGEMENT ====================

class LaybyItemInline(admin.TabularInline):
    model = LaybyItem
    extra = 0

class LaybyPaymentInlineAdmin(admin.TabularInline):
    model = LaybyPayment
    extra = 0

@admin.register(LaybyPlan)
class LaybyPlanAdmin(admin.ModelAdmin):
    list_display = ['id', 'customer', 'status', 'total_price', 'amount_paid', 'due_date', 'created_date']
    list_filter = ['status', 'created_date']
    search_fields = ['customer__name']
    inlines = [LaybyItemInline, LaybyPaymentInlineAdmin]

@admin.register(LaybyPayment)
class LaybyPaymentAdmin(admin.ModelAdmin):
    list_display = ['plan', 'amount', 'payment_date', 'reference']
    list_filter = ['payment_date']

# ==================== CASHBOOK ====================

@admin.register(CashbookEntry)
class CashbookEntryAdmin(admin.ModelAdmin):
    list_display = ['date', 'reference', 'description', 'category', 'receipt_amount', 'payment_amount', 'recorded_by']
    list_filter = ['category', 'date', 'recorded_by']
    search_fields = ['reference', 'description']
    readonly_fields = ['created_date']

@admin.register(BankReconciliation)
class BankReconciliationAdmin(admin.ModelAdmin):
    list_display = ['month', 'opening_balance', 'closing_balance', 'bank_statement_balance', 'difference', 'reconciled']
    list_filter = ['reconciled', 'month']
    readonly_fields = ['difference', 'created_date']

@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ['date', 'category', 'description', 'amount', 'gl_account', 'payment_method', 'reference']
    list_filter = ['category', 'payment_method', 'date']
    search_fields = ['description', 'reference']
