# Enhanced Import Order System - Complete Guide

## 🎉 What's New

Your import order system has been significantly enhanced to match your actual workflow! You can now:

1. **Create products directly while managing import orders** - No more creating inventory first!
2. **Bulk upload products via CSV** - Import dozens of products at once
3. **Automatic landed cost calculation** - System calculates final costs including all expenses
4. **Track product origins** - Know exactly which import order each product came from
5. **Streamlined receiving process** - One-click to receive goods and update stock

---

## 📋 New Workflow

### **Before (Old System)**
```
1. Create products in inventory manually
2. Create import order
3. Link existing products to import order
4. Add expenses
5. Run allocation
6. Update stock manually
```

### **After (New System)**
```
1. Create import order (supplier, dates, currency)
2. Add expenses (shipping, customs, etc.)
3. Add products directly OR bulk upload CSV
4. System auto-calculates landed costs
5. Click "Receive Goods" → Products created & stock updated!
```

---

## 🚀 How to Use

### Method 1: Add Products Manually

1. Go to **Import Orders** → Select or create an order
2. In the **Order Items** section, add a new item
3. Check "**Is New Product**"
4. Fill in product details:
   - Product Name (required)
   - Category
   - Quantity (required)
   - Unit Cost (required)
   - Description, Label, Size, Weight
   - Markup % (optional - uses category default if not set)
5. Save the order

### Method 2: Bulk Upload via CSV

1. Go to **Import Orders** → Select order
2. Click "**Download CSV Template**" to get the format
3. Fill in your products in Excel/CSV editor:
   ```csv
   product_name,category,quantity,unit_cost,description,label,size,weight,markup_percentage
   Red T-Shirt,Clothing,100,5.50,Cotton red t-shirt,RED-TSHIRT,M,0.2,50
   Blue Jeans,Clothing,50,12.00,Denim blue jeans,BLUE-JEANS,L,0.5,45
   ```
4. Save as CSV (UTF-8 encoding)
5. Click "**Bulk Upload**" and select your CSV file
6. System will import all products and show any errors

### Adding Expenses

1. In import order detail, scroll to **Expenses** section
2. Add all costs:
   - Shipping/Freight
   - Customs Duty
   - VAT/Tax
   - Clearing Agent fees
   - Local Transport
   - Insurance
   - Bank charges
3. System tracks each expense separately

### Receiving Goods

When your shipment arrives:

1. Open the import order
2. Click "**Allocate Expenses**" (if not done already)
   - This distributes costs across all products
   - Calculates landed cost per item
3. Click "**Receive Goods**"
   - Creates all new products in inventory
   - Auto-generates product codes
   - Updates stock quantities
   - Sets purchase & selling prices with landed costs
   - Creates stock movement records

Done! Your products are now in inventory and ready to sell!

---

## 📊 CSV Template Format

### Required Fields:
- `product_name` - Name of the product
- `quantity` - How many units ordered
- `unit_cost` - Cost per unit (in import order currency)

### Optional Fields:
- `category` - Product category (created if doesn't exist)
- `description` - Product description
- `label` - Product label (defaults to product_name)
- `size` - Size/dimension
- `weight` - Weight in kg
- `markup_percentage` - Profit margin % (uses category default if empty)

### Example CSV:
```csv
product_name,category,quantity,unit_cost,description,label,size,weight,markup_percentage
Summer Dress,Women's Clothing,150,8.50,"Floral print summer dress",DRESS-SUM-01,M,0.3,55
Men's Shirt,Men's Clothing,200,6.00,"Formal white shirt",SHIRT-WHT-01,L,0.25,50
Sports Shoes,Footwear,80,22.00,"Running shoes with gel sole",SHOE-RUN-01,42,0.75,60
```

---

## 🔍 Key Features

### 1. **Source Tracking**
Every product remembers which import order it came from:
- View in product details
- Useful for warranty claims
- Easy reordering from same supplier

### 2. **Landed Cost Calculation**
System automatically calculates:
```
Landed Cost per Unit = Unit Cost + (Allocated Expenses / Quantity)
Suggested Selling Price = Landed Cost × (1 + Markup %)
```

### 3. **Flexible Allocation Methods**
Choose how to distribute expenses:
- **By Value** (Recommended) - Based on product cost
- **By Quantity** - Equal per unit
- **By Weight** - For heavy items
- **Smart** - System chooses best method
- **Custom** - Set percentages manually

### 4. **Receiving Options**
- Receive all items at once
- Partial receiving (coming soon)
- Adjust quantities if different from order

### 5. **Stock Movements**
Automatic tracking:
- Every receipt creates a stock movement
- Full audit trail
- Linked to import order for reference

---

## 💡 Best Practices

### When Creating Import Orders:

1. **Add ALL expenses upfront** - More accurate costing
2. **Use categories** - Auto-applies correct markup
3. **Check exchange rates** - Update if currency changed
4. **Add supplier reference** - Track their invoice number
5. **Set expected arrival date** - Plan inventory

### For Bulk Uploads:

1. **Start with template** - Ensures correct format
2. **Use UTF-8 encoding** - Prevents character issues
3. **Test with small file first** - 5-10 products
4. **Keep backups** - Save your CSV files
5. **Review after upload** - Check for any errors

### Cost Management:

1. **Allocate before receiving** - Ensures accurate prices
2. **Include all costs** - Don't miss bank fees, tips, etc.
3. **Use local currency** - System converts automatically
4. **Document receipts** - Upload expense receipts
5. **Review markup** - Adjust per product if needed

---

## 🔧 Advanced Features

### Reordering from Supplier

Products remember their source import order, making reordering easy:
1. Find product in inventory
2. View source import order
3. See original supplier and costs
4. Create new import order with same supplier

### Import Order Statuses

- **Draft** - Still adding items
- **Confirmed** - Sent to supplier
- **Shipped** - On the way
- **In Transit** - Tracking available
- **Customs** - Clearing customs
- **Received** - Goods received
- **Completed** - Fully processed

### Expense Allocation Methods Explained

**By Value** (Best for mixed products):
- Product costing $100 gets 2× the expenses of one costing $50
- Fair distribution based on investment

**By Quantity** (Best for similar items):
- Each unit gets equal share
- Simple and straightforward

**By Weight** (Best for freight-heavy):
- Heavier items bear more shipping cost
- Accurate for bulk shipments

**Smart Allocation**:
- System analyzes your order
- Chooses best method automatically
- Considers value, quantity, and weight

---

## 📱 Quick Reference

### Keyboard Shortcuts (Coming Soon)
- `Ctrl + U` - Bulk Upload
- `Ctrl + R` - Receive Goods
- `Ctrl + A` - Allocate Expenses

### Status Indicators
- 🟢 **Green** - Ready to receive
- 🟡 **Yellow** - Awaiting expenses
- 🔵 **Blue** - In transit
- ⚫ **Gray** - Draft/Planning

---

## ❓ Troubleshooting

### CSV Upload Fails?
- **Check encoding** - Must be UTF-8
- **Verify format** - Use provided template
- **Remove special characters** - Stick to alphanumeric
- **Check file size** - Max 5MB

### Products Not Created?
- **Run allocation first** - Expenses must be allocated
- **Check for errors** - Review error messages
- **Verify required fields** - Name, quantity, cost needed

### Wrong Prices?
- **Re-allocate expenses** - Recalculates costs
- **Check markup %** - May need adjustment
- **Verify exchange rate** - Update if changed

### Missing Stock After Receive?
- **Check stock movements** - View audit trail
- **Verify quantities** - May have been adjusted
- **Look for errors** - Check error messages

---

## 🎓 Example Scenario

**You're importing clothes from Turkey:**

1. **Create Import Order**
   - Supplier: "Istanbul Textiles"
   - Order Date: Today
   - Expected Arrival: +30 days
   - Currency: USD
   - Exchange Rate: 1.00 (if using USD locally)

2. **Add Expenses**
   - Shipping: $500
   - Customs Duty: $300
   - Clearing Agent: $100
   - Transport: $50
   - Total Expenses: $950

3. **Bulk Upload Products** (CSV)
   ```csv
   product_name,category,quantity,unit_cost
   T-Shirt Red,Clothing,100,3.50
   T-Shirt Blue,Clothing,150,3.50
   Dress Summer,Clothing,75,8.00
   Jeans Blue,Clothing,50,10.00
   ```

4. **Review Order**
   - 375 total units
   - Goods cost: $1,475
   - Total expenses: $950
   - Total landed cost: $2,425
   - Average cost per unit: $6.47

5. **Allocate & Receive**
   - Click "Allocate Expenses"
   - Click "Receive Goods"
   - ✅ 4 products created
   - ✅ 375 items in stock
   - ✅ Prices set with 50% markup
   - ✅ Ready to sell!

---

## 📞 Support

Need help? Check:
1. This guide first
2. System messages (they're helpful!)
3. CSV template (shows correct format)
4. Error messages (usually very specific)

---

**Version:** 1.0  
**Last Updated:** October 2025  
**Status:** ✅ Production Ready

**Happy Importing! 🚀**