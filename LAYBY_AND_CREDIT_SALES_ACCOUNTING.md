# Layby and Credit Sales Accounting Guide

## Overview

This document explains how the Inventory Management System (IMS) handles layby and credit sales with proper accounting recognition.

## Chart of Accounts

The system uses the following GL account codes:

- **1000** - Cash
- **1200** - Accounts Receivable (AR)
- **1300** - Inventory (Asset)
- **2300** - Unearned Revenue (Liability)
- **4000** - Sales Revenue
- **4800** - Other Income
- **5000** - Cost of Goods Sold (COGS)

## Payment Methods

The system supports three payment methods:

1. **CASH** - Immediate payment and revenue recognition
2. **CREDIT** - Customer buys on account, payment deferred
3. **LAYBY** - Customer reserves goods, pays in installments, goods delivered when fully paid

## Accounting Flows

### 1. CASH Sales

**When sale is made:**
- Stock is reduced immediately
- Journal Entry:
  - Dr Cash (1000) - Sale amount
  - Cr Sales Revenue (4000) - Sale amount
  - Dr COGS (5000) - Cost
  - Cr Inventory (1300) - Cost
- Cashbook receipt entry created
- Sale marked as `posted_to_gl=True` and `posted_to_cashbook=True`

**Implementation:** `accounting.utils.post_cash_sale()`

---

### 2. CREDIT Sales (On Account)

**When sale is made:**
- Stock is reduced immediately (goods delivered)
- ARInvoice created with due date
- Customer balance increased
- Journal Entry:
  - Dr Accounts Receivable (1200) - Sale amount
  - Cr Sales Revenue (4000) - Sale amount
  - Dr COGS (5000) - Cost
  - Cr Inventory (1300) - Cost
- Sale marked as `posted_to_gl=True`
- **No cashbook entry yet** (cash not received)

**Implementation:** `accounting.utils.post_credit_sale()`

**When payment is received:**
- ARPayment record created
- ARInvoice amount_paid updated
- Customer balance reduced
- Journal Entry:
  - Dr Cash (1000) - Payment amount
  - Cr Accounts Receivable (1200) - Payment amount
- Cashbook receipt entry created

**Implementation:** `accounting.models.ARPayment.save()`

---

### 3. LAYBY Sales (Reserve & Pay)

#### Phase 1: Layby Plan Created

**When customer creates layby:**
- Stock is **reserved** (reduced from available inventory)
- LaybyPlan and LaybyItem records created
- Sales record created with `payment_method='LAYBY'`
- **No GL posting yet** (goods not delivered, sale not complete)

#### Phase 2: Customer Makes Deposits

**When each payment/deposit is made:**
- LaybyPayment record created
- LaybyPlan.amount_paid updated
- Journal Entry:
  - Dr Cash (1000) - Deposit amount
  - Cr Unearned Revenue (2300) - Deposit amount
- Cashbook receipt entry created (category='LAYBY')

**Implementation:** `accounting.models.LaybyPayment.save()`

**Important:** Deposits go to **Unearned Revenue** (liability) because:
- Goods have not been delivered yet
- Sale is not complete
- We have an obligation to either deliver goods or refund

#### Phase 3: Layby Fulfillment (Goods Delivered)

**When customer completes payments and picks up goods:**
- Status changed to 'FULFILLED'
- Journal Entry (Revenue Recognition):
  - Dr Unearned Revenue (2300) - Total price
  - Cr Sales Revenue (4000) - Total price
  - Dr COGS (5000) - Total cost
  - Cr Inventory (1300) - Total cost
- Related Sales records marked as `posted_to_gl=True`
- **No cashbook entry** (cash was already recorded with deposits)

**Implementation:** `accounting.views.layby_fulfill_action()`

**Why this approach?**
- Follows accrual accounting principles
- Revenue recognized when **earned** (goods delivered)
- Matches revenue with related costs (COGS)
- Unearned revenue liability cleared

#### Phase 4: Layby Cancellation (Optional)

**When customer cancels layby:**
- Stock restored (added back to inventory)
- Cancellation fee calculated (if any)
- Journal Entries:
  - **Refund portion:**
    - Dr Unearned Revenue (2300) - Refund amount
    - Cr Cash (1000) - Refund amount
  - **Forfeit fee portion:**
    - Dr Unearned Revenue (2300) - Fee amount
    - Cr Other Income (4800) - Fee amount
- Cashbook payment entry for refund
- Status changed to 'CANCELLED'

**Implementation:** `accounting.views.layby_cancel_action()`

---

## Key Accounting Principles

### 1. Revenue Recognition
- **Cash:** Revenue recognized immediately (delivered + paid)
- **Credit:** Revenue recognized at sale (delivered, payment pending)
- **Layby:** Revenue recognized at fulfillment (paid, then delivered)

### 2. Matching Principle
- COGS always posted together with revenue recognition
- Ensures proper profit calculation

### 3. Unearned Revenue
- Layby deposits create a **liability** (obligation to deliver)
- Liability converted to revenue only when goods delivered
- Proper cancellation handling with refunds/forfeits

### 4. Accounts Receivable
- Credit sales create AR asset (right to receive payment)
- Customer balance tracked
- Credit limits enforced
- AR reduced when payments received

### 5. Cashbook Tracking
- All cash movements recorded in cashbook
- Cash sales → Receipt
- Layby deposits → Receipt
- AR payments → Receipt
- Layby refunds → Payment
- Enables cash flow analysis

---

## Reports and Visibility

### Sales Report
- Shows all sales by payment method (CASH, CREDIT, LAYBY)
- Layby sales remain marked as 'LAYBY' for reporting
- Can distinguish between different revenue streams

### Cashbook
- All cash receipts and payments
- Running balance
- Categories: SALES, AR, LAYBY, EXPENSE

### Accounts Receivable Aging
- Outstanding invoices
- Due dates and overdue amounts
- Customer balances

### Layby Management
- Active plans
- Payment progress
- Due dates
- Fulfillment tracking

---

## Database Fields

### Sales Model
- `payment_method`: 'CASH', 'CREDIT', or 'LAYBY'
- `posted_to_gl`: Prevents duplicate GL postings
- `posted_to_cashbook`: Prevents duplicate cashbook entries
- `customer`: Links to Customer (required for CREDIT and LAYBY)

### LaybyPlan Model
- `status`: 'ACTIVE', 'FULFILLED', 'CANCELLED', 'DEFAULTED'
- `total_price`: Total amount due
- `amount_paid`: Sum of all payments/deposits
- `customer`: Who is making the layby

### ARInvoice Model
- `status`: 'PENDING', 'PARTIAL', 'PAID', 'OVERDUE', 'CANCELLED'
- `total_amount`: Invoice total
- `amount_paid`: Payments received
- `outstanding_amount`: Property (total - paid)

---

## Testing Checklist

### CASH Sale
- [ ] Stock reduces correctly
- [ ] GL entry: Dr Cash, Cr Revenue, Dr COGS, Cr Inventory
- [ ] Cashbook receipt created
- [ ] Sale marked as posted

### CREDIT Sale
- [ ] Stock reduces correctly
- [ ] ARInvoice created
- [ ] Customer balance increases
- [ ] GL entry: Dr AR, Cr Revenue, Dr COGS, Cr Inventory
- [ ] NO cashbook entry yet

### CREDIT Payment
- [ ] ARPayment created
- [ ] ARInvoice updated
- [ ] Customer balance decreases
- [ ] GL entry: Dr Cash, Cr AR
- [ ] Cashbook receipt created

### LAYBY Creation
- [ ] Stock reserved (reduces)
- [ ] LaybyPlan created
- [ ] NO GL or cashbook entry yet

### LAYBY Deposit
- [ ] LaybyPayment created
- [ ] Plan amount_paid updates
- [ ] GL entry: Dr Cash, Cr Unearned Revenue
- [ ] Cashbook receipt created

### LAYBY Fulfillment
- [ ] Plan status = FULFILLED
- [ ] GL entry: Dr Unearned Revenue, Cr Revenue, Dr COGS, Cr Inventory
- [ ] Sales marked as posted
- [ ] NO cashbook entry (already recorded)

### LAYBY Cancellation
- [ ] Stock restored
- [ ] GL entries for refund and/or forfeit fee
- [ ] Cashbook payment for refund
- [ ] Plan status = CANCELLED

---

## Common Issues and Solutions

### Issue: Import errors for GLAccount, JournalEntry, JournalLine
**Solution:** These are in `accounting.models`, not `inventory.models`. Fixed in views.py.

### Issue: Duplicate GL postings
**Solution:** Use `posted_to_gl` flag on Sales model to prevent re-posting.

### Issue: Revenue recognized too early on layby
**Solution:** Post to Unearned Revenue liability first, recognize revenue only on fulfillment.

### Issue: Inconsistent inventory GL account codes
**Solution:** Standardized to code '1300' across all modules (utils.py and views.py).

### Issue: Layby deposits not appearing in cashbook
**Solution:** LaybyPayment.save() now creates CashbookEntry with category='LAYBY'.

---

## Future Enhancements

1. **Partial Layby Fulfillment** - Allow delivery of some items while others still pending
2. **Payment Plan Templates** - Pre-defined installment schedules
3. **Automated Reminders** - Email/SMS for overdue AR and layby payments
4. **Interest Charges** - Late payment fees for overdue AR
5. **Loyalty Points** - Integration with customer loyalty program
6. **Multi-Currency** - Support for foreign currency sales
7. **Sales Returns** - Proper accounting for returned goods (Cr Revenue, Dr AR/Cash)

---

## Support

For questions or issues, refer to:
- Django models: `accounting/models.py`, `inventory/models.py`
- Accounting utilities: `accounting/utils.py`
- Views: `accounting/views.py`, `inventory/views.py`
- This documentation: `LAYBY_AND_CREDIT_SALES_ACCOUNTING.md`
