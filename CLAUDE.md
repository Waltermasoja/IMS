# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Django-based Inventory Management System (IMS) with comprehensive accounting, POS, and import order management capabilities. The system handles cash sales, credit sales, layby plans, and full accrual accounting with General Ledger integration.

**Django Project:** `inventorySystem`
**Main Apps:** `inventory`, `accounting`
**Database:** SQLite (development), MySQL/PostgreSQL (production ready)

## Development Commands

### Setup & Installation

```bash
# Install dependencies (recommended: use virtual environment)
pip install -r requirements.txt

# First-time setup: Run migrations
python manage.py migrate

# CRITICAL: Initialize GL accounts (required for accounting features)
python manage.py init_gl_accounts

# Create superuser
python manage.py createsuperuser
```

### Running the Server

```bash
# Development server
python manage.py runserver

# Access at: http://127.0.0.1:8000/
# Admin panel: http://127.0.0.1:8000/admin/
```

### Database Operations

```bash
# Create migrations after model changes
python manage.py makemigrations

# Apply migrations
python manage.py migrate

# Database shell
python manage.py dbshell
```

### Django Shell

```bash
# Access Django shell for testing
python manage.py shell
```

## High-Level Architecture

### Two-App Structure

1. **`inventory/` app** - Core inventory, sales, POS, import orders, customers, suppliers
2. **`accounting/` app** - General Ledger, Journal Entries, AR/AP, Layby, Cashbook, Expenses

### Key Model Relationships

**Inventory Flow:**
- `Inventory` (products) ← `ImportOrder` (supplier orders with landed cost) ← `Supplier`
- `Sales` ← `Inventory` (many-to-one: each sale references one product)
- `StockMovement` tracks all IN/OUT inventory changes

**Accounting Flow:**
- `Sales` → triggers `JournalEntry` with `JournalLine` records → updates `GLAccount` balances
- Payment methods: CASH, CREDIT, LAYBY determine accounting treatment
- All GL postings use `accounting/utils.py` functions: `post_cash_sale()`, `post_credit_sale()`, `post_layby_fulfillment()`

**Customer Credit & AR:**
- `Sales` (payment_method=CREDIT) → creates `ARInvoice` → updates `Customer.current_balance`
- `ARPayment` → reduces invoice balance → posts: Dr Cash, Cr AR

**Layby System:**
- `LaybyPlan` → contains `LaybyItem` (reserved products)
- `LaybyPayment` → deposits: Dr Cash, Cr Unearned Revenue (2300)
- Fulfillment → recognizes revenue: Dr Unearned Revenue, Cr Sales Revenue (4000) + COGS

### Chart of Accounts Structure

The system uses a standard account code structure:
- **1000** - Cash (asset)
- **1200** - Accounts Receivable (asset)
- **1300** - Inventory (asset)
- **2300** - Unearned Revenue (liability - layby deposits)
- **4000** - Sales Revenue (income)
- **4800** - Other Income (income)
- **5000** - Cost of Goods Sold / COGS (expense)
- **6000-6900** - Operating expenses (rent, utilities, wages, freight, etc.)

**CRITICAL:** GL accounts MUST be initialized using `python manage.py init_gl_accounts` before processing sales.

### Revenue Recognition by Payment Method

**CASH Sales:**
1. Sale made → stock reduced immediately
2. GL: Dr Cash (1000), Cr Sales Revenue (4000)
3. GL: Dr COGS (5000), Cr Inventory (1300)
4. Cashbook: Receipt entry created
5. Flags: `posted_to_gl=True`, `posted_to_cashbook=True`

**CREDIT Sales (On Account):**
1. Sale made → stock reduced immediately (goods delivered)
2. `ARInvoice` created with due date
3. `Customer.current_balance` increased
4. GL: Dr Accounts Receivable (1200), Cr Sales Revenue (4000)
5. GL: Dr COGS (5000), Cr Inventory (1300)
6. NO cashbook entry yet (cash not received)
7. When payment received → GL: Dr Cash (1000), Cr AR (1200) + cashbook receipt

**LAYBY Sales (Reserve & Pay):**
1. Plan created → stock reserved (quantity reduced)
2. NO GL posting yet (goods not delivered)
3. Each deposit → GL: Dr Cash (1000), Cr Unearned Revenue (2300) + cashbook receipt
4. Fulfillment → GL: Dr Unearned Revenue (2300), Cr Sales Revenue (4000)
5. Fulfillment → GL: Dr COGS (5000), Cr Inventory (1300)
6. NO cashbook entry on fulfillment (cash already recorded with deposits)

### Import Order & Landed Cost System

**Purpose:** Calculate true product cost including freight, customs, duties, insurance.

**Workflow:**
1. Create `ImportOrder` with `Supplier`, currency, exchange rate
2. Add `ImportOrderItem` entries (can be existing products or new products)
3. Add `ImportExpense` records (shipping, customs duty, clearing fees, etc.)
4. Run allocation → distributes expenses across items (by value/weight/quantity)
5. Each item gets `landed_cost_per_unit` = unit_cost + (allocated_expenses / quantity)
6. Receive goods → updates `Inventory.purchase_price` and `quantity_in_Stock`
7. `suggested_selling_price` calculated with markup percentage

**Allocation Methods:**
- VALUE (recommended) - distribute by purchase value
- QUANTITY - equal per item
- WEIGHT - by weight
- SMART - hybrid approach

### POS & Sales Flow

**Entry Point:** `inventory/views.py` → `make_sale()` function

**Process:**
1. User selects product (by name or product_code)
2. Enters quantity, optional discount
3. Selects payment method: CASH, CREDIT, or LAYBY
4. System validates:
   - Stock availability
   - Credit limit (if CREDIT)
   - Customer exists (if CREDIT/LAYBY)
5. Sale created → triggers accounting via `accounting/utils.py`
6. Stock reduced via `StockMovement`
7. Receipt number generated

**IMPORTANT FLAGS on Sales model:**
- `posted_to_gl` - prevents duplicate journal entries
- `posted_to_cashbook` - prevents duplicate cashbook entries

### Template Structure

Templates are in `templates/` directory (root level, shared across apps):
- `templates/base.html` - Base template with navigation
- `templates/inventory/*.html` - POS, inventory lists, reports, sales
- `templates/accounting/*.html` - AR, layby, expenses, cashbook

CSS framework: Bootstrap 4 with Crispy Forms

### User Roles & Permissions

`inventory.models.UserProfile` extends Django User with:
- Roles: admin, manager, sales, viewer
- POS permissions: can_make_sales, can_process_returns, can_apply_discounts
- max_discount_percent (user-specific limit)
- Access control: can_view_reports, can_manage_inventory, can_manage_suppliers

## Common Development Patterns

### Creating a New Sale with Accounting

```python
from inventory.models import Sales, Inventory
from accounting.utils import post_cash_sale

# Create sale
sale = Sales.objects.create(
    inventory_item=item,
    quantity_sold=5,
    sale_price=item.selling_price,
    payment_method='CASH',
    customer=customer,  # optional for CASH
    recorded_by=request.user
)

# Post accounting (for CASH sales)
post_cash_sale(sale)
```

### Adding GL Journal Entries

```python
from accounting.models import GLAccount, JournalEntry, JournalLine

# Always use transaction.atomic for GL posting
from django.db import transaction

with transaction.atomic():
    je = JournalEntry.objects.create(
        memo="Description of transaction",
        reference="REF-001",
        created_by=user
    )

    # Debit side
    JournalLine.objects.create(
        entry=je,
        account=GLAccount.objects.get(code='1000'),  # Cash
        debit=100.00,
        description="Cash received"
    )

    # Credit side
    JournalLine.objects.create(
        entry=je,
        account=GLAccount.objects.get(code='4000'),  # Revenue
        credit=100.00,
        description="Sales revenue"
    )
```

### Import Order Workflow

```python
# 1. Create order
order = ImportOrder.objects.create(
    supplier=supplier,
    order_date=date.today(),
    expected_arrival=date.today() + timedelta(days=30),
    currency='USD',
    exchange_rate=Decimal('25.50'),
    allocation_method='SMART'
)

# 2. Add items
ImportOrderItem.objects.create(
    import_order=order,
    inventory_item=product,
    quantity=100,
    unit_cost=Decimal('10.00')
)

# 3. Add expenses
ImportExpense.objects.create(
    import_order=order,
    expense_type='SHIPPING',
    description='Sea freight',
    amount=Decimal('500.00'),
    currency='USD'
)

# 4. Run allocation (distributes expenses)
from inventory.utils import run_allocation
run_allocation(order)

# 5. Receive goods
order.receive_all_goods()  # Updates stock quantities
```

## Important Files & Locations

**Models:**
- `inventory/models.py` - Inventory, Sales, Customer, Supplier, ImportOrder, StockMovement
- `accounting/models.py` - GLAccount, JournalEntry, ARInvoice, LaybyPlan, CashbookEntry, Expense

**Business Logic:**
- `accounting/utils.py` - Core accounting functions (post_cash_sale, post_credit_sale, post_layby_fulfillment)
- `inventory/views.py` - POS, sales, import orders, reports
- `accounting/views.py` - AR, layby management, cashbook, expenses

**URL Routing:**
- `inventorySystem/urls.py` - Root URL config
- `inventory/urls.py` - Inventory app URLs
- `accounting/urls.py` - Accounting app URLs

**Settings:**
- `inventorySystem/settings.py` - Django settings (DB config, installed apps, static files)

**Management Commands:**
- `accounting/management/commands/init_gl_accounts.py` - Initialize chart of accounts

## Critical Business Rules

1. **Accrual Accounting:** Revenue is recognized when earned (goods delivered), not when cash received
2. **Layby deposits are liabilities** until goods delivered (Unearned Revenue account)
3. **Credit limit enforcement:** Check `Customer.current_balance` < `Customer.credit_limit` before credit sale
4. **COGS must be posted** with every revenue recognition (matching principle)
5. **Stock movements logged:** All quantity changes create `StockMovement` record
6. **Idempotent GL posting:** Use `posted_to_gl` flag to prevent duplicate journal entries
7. **Landed cost affects profit margins:** Import order expenses distributed to products before setting selling price

## Known Issues & Setup Requirements

### MUST DO on Fresh Installation

1. Run `python manage.py init_gl_accounts` - Creates required GL accounts
2. Verify GL accounts exist before testing sales (check admin panel)
3. Configure exchange rates in `ImportOrder` for foreign currency

### Import Errors to Avoid

- `GLAccount`, `JournalEntry`, `JournalLine` are in `accounting.models` (NOT `inventory.models`)
- Always import from correct app: `from accounting.models import GLAccount`

### Console Logging

The system uses console logging with prefixes for debugging:
- `[LAYBY]` - Layby-related operations
- `[CREDIT]` - Credit sales operations
- `[LAYBY][MODEL][WARN]` - Warnings (e.g., GL accounts missing)

## Deployment Considerations

**Supported Databases:**
- Development: SQLite (default)
- Production: MySQL or PostgreSQL (config in settings.py, lines 100-116)

**Static Files:**
- Uses WhiteNoise for serving static files
- Run `python manage.py collectstatic` before deployment

**Environment:**
- SECRET_KEY should be changed in production (settings.py:25)
- DEBUG should be False in production (settings.py:28)
- Configure ALLOWED_HOSTS for production domain (settings.py:38-43)

## Testing & Debugging

### Check GL Account Setup

```python
python manage.py shell
>>> from accounting.models import GLAccount
>>> GLAccount.objects.filter(code__in=['1000','1200','1300','2300','4000','5000'])
# Should return 6 accounts
```

### Verify Sale Accounting

```python
# After making a sale
>>> from inventory.models import Sales
>>> sale = Sales.objects.latest('sale_date')
>>> sale.posted_to_gl  # Should be True
>>> sale.posted_to_cashbook  # Should be True (for CASH sales)
```

### Check Journal Entry Balance

```python
>>> from accounting.models import JournalEntry
>>> je = JournalEntry.objects.latest('posted_at')
>>> je.is_balanced  # Should be True (debits == credits)
```

## Documentation References

See project documentation files for detailed guides:
- `FIXES_AND_SETUP.md` - Setup instructions and troubleshooting
- `LAYBY_AND_CREDIT_SALES_ACCOUNTING.md` - Complete accounting flow documentation
- `IMPORT_ORDER_GUIDE.md` - Import order system guide
- `INVOICE_SYSTEM_GUIDE.md` - Invoice and AR system guide
