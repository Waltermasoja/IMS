# IMS Layby & Credit Sales - Fixes Applied

## Summary of Changes

### 1. Fixed Import Errors ✅
**File:** `accounting/views.py`

**Problem:** Incorrect imports on lines 25 and 77
- `GLAccount`, `JournalEntry`, `JournalLine` were being imported from `inventory.models` 
- These models are actually in `accounting.models`

**Fix:** 
- Removed incorrect imports from `inventory.models`
- Now only import `Sales` and `StockMovement` from inventory
- GL accounting models are already imported at top of file from `.models`

### 2. Improved Layby Fulfillment ✅
**File:** `accounting/views.py` - `layby_fulfill_action()` function

**Improvements:**
- Added `transaction.atomic()` for data integrity
- Standardized GL account codes (1300 for Inventory)
- Better error handling with user messages
- Proper revenue recognition: Dr Unearned Revenue → Cr Sales Revenue
- COGS recognition: Dr COGS → Cr Inventory
- Mark sales as `posted_to_gl=True` to prevent duplicates

### 3. Updated Layby UI ✅
**File:** `accounting/templates/accounting/layby_list.html`

**Changes:**
- Removed "Fulfill" button from table rows
- Added "Add Payment" button for active layby plans
- Fulfill action now only available on detail page
- Cleaner, more intuitive workflow

### 4. Enhanced Credit Sales Logging ✅
**File:** `inventory/views.py` - `make_sale()` function

**Improvements:**
- Added detailed console logging for debugging
- Better error messages for customers
- Improved validation and error handling
- Shows available credit when limit exceeded

### 5. Created GL Account Setup Tool ✅
**New Files:**
- `accounting/management/commands/init_gl_accounts.py`
- `accounting/management/__init__.py`
- `accounting/management/commands/__init__.py`

**Purpose:** Django management command to initialize all required GL accounts

---

## Required Setup Steps

### Step 1: Initialize GL Accounts (IMPORTANT!)

The warning you saw: `[LAYBY][MODEL][WARN] GL accounts for cash/unearned not found`

This means the GL accounts don't exist yet. Run this command:

```bash
python manage.py init_gl_accounts
```

This will create all required accounts:
- **1000** - Cash
- **1200** - Accounts Receivable
- **1300** - Inventory
- **2300** - Unearned Revenue
- **4000** - Sales Revenue
- **4800** - Other Income
- **5000** - Cost of Goods Sold (COGS)
- Plus expense accounts (6000-6900)

### Step 2: Test Layby Flow

1. **Create a layby plan** (POS → select product → Payment Method: Layby)
   - Provide customer, deposit amount
   - Check console: Should see `[LAYBY]` log messages
   - Verify: Stock reserved, cashbook receipt created

2. **Add payment** (Layby List → Add Payment button)
   - Make additional payment
   - Check: GL entry Dr Cash, Cr Unearned Revenue
   - Verify: Cashbook receipt created

3. **Fulfill layby** (Layby Detail page → Fulfill button)
   - Check console: Should NOT see GL account warnings
   - Verify: Revenue recognized from Unearned to Sales Revenue
   - Verify: COGS posted (Dr COGS, Cr Inventory)

### Step 3: Test Credit Sales

1. **Create a credit sale** (POS → select product → Payment Method: Credit)
   - Provide customer and due date
   - Watch console for `[CREDIT]` log messages
   - If it fails, check the error message and console output

2. **Verify accounting:**
   - ARInvoice created
   - Customer balance increased
   - GL entry: Dr Accounts Receivable, Cr Sales Revenue
   - GL entry: Dr COGS, Cr Inventory
   - Stock reduced immediately

3. **Record payment** (AR List → enter payment amount → Pay button)
   - Check: ARInvoice amount_paid updates
   - Check: Customer balance decreases
   - Check: GL entry Dr Cash, Cr AR
   - Check: Cashbook receipt created

### Step 4: Verify Reports

1. **Cashbook** (`/accounting/cashbook/`)
   - Should show all cash receipts: Cash sales, Layby deposits, AR payments
   - Should show all payments: Expenses, Layby refunds

2. **Sales Report** (`/inventory/sales/report/`)
   - Should show sales by payment method (CASH, CREDIT, LAYBY)
   - Daily breakdown

3. **AR Aging** (`/inventory/ar/`)
   - Outstanding invoices
   - Overdue invoices highlighted
   - Total outstanding balance

---

## Troubleshooting

### Problem: "GL accounts not found" warning persists
**Solution:** Run `python manage.py init_gl_accounts` to create accounts

### Problem: Credit sale returns "Customer not found"
**Solution:** 
1. Check if customer exists: `/inventory/customers/`
2. Verify customer_id is being sent in POST request
3. Check console for `[CREDIT][ERROR]` messages

### Problem: "Credit limit exceeded"
**Solution:**
1. Go to customer detail page
2. Increase `credit_limit` field
3. Or collect payment to reduce `current_balance`

### Problem: Layby not creating GL entries
**Solution:**
1. Verify GL accounts exist (run init command)
2. Check account codes match: 1000, 2300, 4000, 5000, 1300
3. Look for `[LAYBY][MODEL][WARN]` messages in console

### Problem: Duplicate journal entries
**Solution:** 
- System now uses `posted_to_gl` flag on Sales model
- Entries only posted once per sale
- If duplicates exist, they're from before this fix

---

## How the Accounting Works

### Cash Sales
1. Sale made → Stock reduces
2. GL: Dr Cash 1000, Cr Revenue 4000
3. GL: Dr COGS 5000, Cr Inventory 1300
4. Cashbook: Receipt entry
5. Done! Revenue recognized immediately

### Credit Sales (On Account)
1. Sale made → Stock reduces
2. GL: Dr AR 1200, Cr Revenue 4000
3. GL: Dr COGS 5000, Cr Inventory 1300
4. Customer balance increases
5. **No cashbook entry** (cash not yet received)

**When payment received:**
1. GL: Dr Cash 1000, Cr AR 1200
2. Customer balance decreases
3. Cashbook: Receipt entry

### Layby Sales
**Phase 1 - Create Plan:**
1. Stock reserved (reduced)
2. No GL entries yet

**Phase 2 - Deposits:**
1. Each deposit: GL Dr Cash 1000, Cr Unearned Revenue 2300
2. Cashbook: Receipt entry
3. Deposits accumulate as **liability** (we owe goods or refund)

**Phase 3 - Fulfillment:**
1. GL: Dr Unearned Revenue 2300, Cr Sales Revenue 4000
2. GL: Dr COGS 5000, Cr Inventory 1300
3. Revenue recognized when **earned** (goods delivered)
4. No cashbook entry (cash already recorded)

---

## Files Modified

1. `accounting/views.py` - Fixed imports, improved layby_fulfill_action
2. `accounting/templates/accounting/layby_list.html` - UI improvements
3. `inventory/views.py` - Enhanced credit sales logging
4. `accounting/management/commands/init_gl_accounts.py` - **NEW** GL setup tool

## Documentation Created

1. `LAYBY_AND_CREDIT_SALES_ACCOUNTING.md` - Complete accounting guide
2. `FIXES_AND_SETUP.md` - This file (setup instructions)

---

## Next Steps

1. ✅ Run `python manage.py init_gl_accounts`
2. ✅ Restart Django server
3. ✅ Test layby flow (create → deposit → fulfill)
4. ✅ Test credit flow (create → verify AR → record payment)
5. ✅ Check reports (cashbook, sales, AR aging)
6. 📧 If issues persist, check console logs and report specific error messages

---

## Support

For detailed accounting principles and flows, see:
- `LAYBY_AND_CREDIT_SALES_ACCOUNTING.md`

For code reference:
- Models: `accounting/models.py`, `inventory/models.py`
- Utilities: `accounting/utils.py`
- Views: `accounting/views.py`, `inventory/views.py`
