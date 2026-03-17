# Invoice System - Quick Start Guide

## ✅ System is Now Live!

The invoice generator with customer loyalty tracking is now fully integrated into your IMS system.

## 🎯 Key Features

### 1. **Customer Management**
- **Email Opt-in**: Customers can choose to receive email invoices
- **Purchase Tracking**: Automatic loyalty counter for all purchases
- **Optional for Cash**: Customer info is optional for cash sales but captured for loyalty

### 2. **Point of Sale (POS)**
- Access via: **Navigation Menu → Sales Summary** or direct at `/inventory/pos/`
- Customer selection now available for ALL payment methods:
  - **Cash**: Optional (for loyalty tracking)
  - **Credit**: Required
  - **Layby**: Required
- **Add New Customer** button in POS with email opt-in checkbox

### 3. **Invoice Generation**
- Access via: **Navigation Menu → Invoices → Generate Invoice**
- Select multiple sales to combine into one invoice
- Choose existing customer or add new one
- Auto-emails if customer opted in

### 4. **Invoice Management**
- **View All Invoices**: Navigate to "Invoices" in sidebar
- **Filter by**: Customer, date range, email status
- **Actions**: View, Print, Send Email

## 📍 How to Use

### Making a Sale with Customer (POS)

1. Navigate to POS interface
2. Search and add products to cart
3. Select payment method
4. **For ALL methods**: You can now select or add a customer
   - **Cash**: Customer is optional (shows "Optional - for loyalty")
   - **Credit/Layby**: Customer is required
5. Click **+ New** to add customer with email opt-in
6. Complete sale

### Generating an Invoice

1. Go to **Invoices → Generate Invoice**
2. Select customer (or add new, or leave blank for walk-in)
3. Check boxes next to sales to include
4. Click **Generate Invoice**
5. If customer has email opt-in, invoice emails automatically

### Viewing Invoices

1. Go to **Invoices** in navigation
2. Filter by customer, date, or email status
3. Click invoice number to view details
4. Use **Print** or **Send Email** buttons as needed

### Managing Customers

1. Go to **Customers** in navigation
2. View purchase count and email opt-in status
3. Edit customer to update opt-in preferences

## 🔍 Where Everything Is

### Navigation Menu (Sidebar)
```
├── Dashboard
├── Inventory  
├── Sales
├── Invoices ⭐ NEW
├── Customers ⭐ NEW
├── Categories
└── Reports
```

### URLs
- **Invoices List**: `/inventory/invoices/`
- **Generate Invoice**: `/inventory/invoices/generate/`
- **Customers**: `/inventory/customers/`
- **POS**: `/inventory/pos/`

## 💡 Tips

1. **For Cash Sales**: 
   - You can now capture customer info to track purchases for loyalty
   - Customer is optional but recommended for repeat customers

2. **Email Invoices**:
   - Only sends if customer has email AND opted in
   - Check the envelope icon (✉) in customer list to see who's opted in

3. **Purchase Count**:
   - Automatically increments when invoice is created with customer
   - Visible in customer list and detail pages
   - Use for loyalty tiers, discounts, etc.

4. **Invoice Numbers**:
   - Auto-generated as `INV-YYYY-NNNN`
   - Example: `INV-2025-0001`

## 🎨 What You See

### POS Interface
- Customer field now shows for **all** payment types
- Label changes:
  - Cash: "Customer (Optional - for loyalty)"
  - Credit/Layby: "Customer *Required"
- Checkbox in new customer form: "Customer agrees to receive email invoices"

### Invoice List
- Filter by customer, dates, email status
- Icons: 👁️ View | 🖨️ Print | ✉️ Email
- Email icon only shows if customer opted in

### Customer List
- Shows purchase count
- Shows email opt-in status
- Purchase counter visible for loyalty programs

## 📧 Email Configuration (Optional)

If you want to send emails, configure in `settings.py`:

```python
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'  # or your SMTP host
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = 'your-email@gmail.com'
EMAIL_HOST_PASSWORD = 'your-app-password'
DEFAULT_FROM_EMAIL = 'your-email@gmail.com'
```

## ✨ Summary

Your invoice system is **ready to use**! 

- ✅ Customer info can be captured for ALL sales (optional for cash)
- ✅ Email opt-in tracked per customer
- ✅ Purchase counter for loyalty programs
- ✅ Invoices accessible from navigation menu
- ✅ Auto-email for opted-in customers
- ✅ Professional printable invoices

Start using it by:
1. Going to POS and making a sale with customer info
2. Or go to Invoices → Generate Invoice to create one from existing sales

Enjoy your new invoice system! 🎉
