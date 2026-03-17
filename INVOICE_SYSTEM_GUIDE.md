# Sales Invoice Generator System

## Overview
A complete invoice generation system for customer sales with email functionality and loyalty tracking. The system supports cash sales (optional customer), credit sales, and layby purchases.

## Features Implemented

### 1. Customer Management Enhancements
- **Email Opt-in**: Boolean field to track customer consent for email invoices
- **Purchase Counter**: Automatic tracking of total purchases for loyalty programs
- Both fields are optional for cash sales but can be captured for loyalty tracking

### 2. Invoice Models

#### SalesInvoice
- Auto-generated invoice numbers (INV-YYYY-NNNN format)
- Optional customer linkage (supports walk-in customers)
- Tracks subtotal, tax, discounts, and total amounts
- Email tracking (sent status and timestamp)
- Created by user tracking

#### SalesInvoiceItem
- Line items with product details
- Links to original Sales records
- Stores quantity, unit price, discounts, and line totals
- Historical record (product name/code stored even if product changes)

### 3. Business Logic

#### Customer Requirements
- **Cash Sales**: Customer is optional
  - Can add customer later for loyalty tracking
  - Invoice generated without customer details
  
- **Credit/Layby Sales**: Customer is REQUIRED
  - System enforces customer association
  - Required for tracking outstanding balances
  - Purchase count automatically incremented

#### Email Functionality
- Automatic email sending when invoice is created (if customer opted in)
- Manual email sending from invoice list or detail pages
- Only sends if:
  1. Customer exists
  2. Customer has email address
  3. Customer opted in for emails
- Tracks email sent status and timestamp

### 4. Loyalty Program Support
- `purchase_count` field tracks total number of purchases
- Automatically incremented when invoice is created with customer
- Visible in customer list and detail views
- Can be used for:
  - Loyalty tiers
  - Discount eligibility
  - Customer insights

## Files Created/Modified

### Models (`inventory/models.py`)
```python
# Customer model additions
- opt_in_for_emails: BooleanField
- purchase_count: IntegerField

# New models
- SalesInvoice
- SalesInvoiceItem
```

### Views (`inventory/invoice_views.py`)
- `invoice_list`: List all invoices with filters
- `invoice_detail`: View single invoice
- `generate_invoice_from_sales`: Create invoice from sales
- `send_invoice_email`: Send invoice via email (AJAX)
- `print_invoice`: Printable invoice view
- `customer_invoices`: View all invoices for a customer

### Forms (`inventory/forms.py`)
- Updated `CustomerForm` with opt_in_for_emails
- New `QuickCustomerForm` for POS customer creation

### Admin (`inventory/admin.py`)
- Added SalesInvoice and SalesInvoiceItem to admin
- Updated CustomerAdmin to show purchase_count and opt_in_for_emails
- Inline editing for invoice items

### Templates
- `invoice_list.html`: Invoice listing with filters
- `invoice_detail.html`: Full invoice view with email functionality

## Usage

### Creating an Invoice

1. **From Sales History**:
   ```
   Navigate to Sales → Select sales → Generate Invoice
   ```

2. **Select or Add Customer**:
   - Choose existing customer from dropdown, OR
   - Check "Add New Customer" and fill quick form
   - For cash sales, leave customer blank

3. **Email Options**:
   - If customer opted in: Invoice emails automatically
   - If not opted in: Manual email button available later

### Viewing Invoices

1. Navigate to Invoices list
2. Filter by:
   - Customer
   - Date range
   - Email status (sent/not sent)

3. Actions available:
   - View details
   - Print
   - Send email (if applicable)

### Customer Opt-in Management

**When adding/editing customers:**
- Check "Email opt-in for invoices" if customer consents
- Required for automatic invoice emailing
- Can be updated anytime in customer profile

## Database Migration

Migration created: `0018_customer_opt_in_for_emails_customer_purchase_count_and_more.py`

Adds:
- Customer.opt_in_for_emails (default: False)
- Customer.purchase_count (default: 0)
- Sales.customer foreign key
- SalesInvoice model
- SalesInvoiceItem model

## Next Steps (To Complete)

### 1. URL Configuration
Add to `inventory/urls.py`:
```python
from .invoice_views import (
    invoice_list, invoice_detail, generate_invoice_from_sales,
    send_invoice_email, print_invoice, customer_invoices
)

urlpatterns += [
    path('invoices/', invoice_list, name='invoice_list'),
    path('invoices/<int:invoice_id>/', invoice_detail, name='invoice_detail'),
    path('invoices/generate/', generate_invoice_from_sales, name='generate_invoice'),
    path('invoices/<int:invoice_id>/send-email/', send_invoice_email, name='send_invoice_email'),
    path('invoices/<int:invoice_id>/print/', print_invoice, name='print_invoice'),
    path('customers/<int:customer_id>/invoices/', customer_invoices, name='customer_invoices'),
]
```

### 2. Email Configuration
Configure email settings in `settings.py`:
```python
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'your-smtp-host'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = 'your-email@example.com'
EMAIL_HOST_PASSWORD = 'your-password'
DEFAULT_FROM_EMAIL = 'your-email@example.com'
```

### 3. Create Email Template
Create `templates/inventory/invoice_email.html` for email body

### 4. Create Print Template
Create `templates/inventory/invoice_print.html` for printable invoices

### 5. Update POS/Sales View
Integrate customer selection during sales process in the make_sale view

### 6. Add Navigation Links
Add invoice links to your navigation menu

## Benefits

1. **Flexibility**: Optional customer for cash, required for credit/layby
2. **Compliance**: Email opt-in tracked per customer
3. **Loyalty**: Purchase count for loyalty programs
4. **Automation**: Auto-email on invoice creation
5. **History**: Complete audit trail of invoices and emails sent
6. **Professional**: Clean, printable invoices for customers

## Technical Notes

- Invoice numbers are auto-generated and unique
- Purchase count increments only when customer is associated
- Email sending is non-blocking (won't fail invoice creation)
- All customer data is optional for cash sales
- System supports both walk-in and registered customers
