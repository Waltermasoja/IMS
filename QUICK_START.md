# Quick Start Guide - Modern IMS 🚀

## Test the New Design in 2 Minutes

### Step 1: Backup Current Files (Optional but Recommended)
```bash
cd C:\Users\Kudzai Bosha\Documents\GitHub\IMS
mkdir templates_backup
cp templates/base.html templates_backup/
cp templates/inventory/dashboard.html templates_backup/
cp templates/inventory/inventory_list.html templates_backup/
```

### Step 2: Option A - Direct Replacement (Fast)
```bash
# Replace base template
cp templates/base_modern.html templates/base.html

# Replace dashboard
cp templates/inventory/dashboard_modern.html templates/inventory/dashboard.html

# Replace inventory list
cp templates/inventory/inventory_list_modern.html templates/inventory/inventory_list.html
```

### Step 3: Restart Server
```bash
# Activate virtual environment
.\venv\Scripts\Activate.ps1

# Run server
python manage.py runserver
```

### Step 4: Open Browser
Go to: http://127.0.0.1:8000/

---

## 🎯 What to Test

### Dashboard
- ✅ Check metric cards display correctly
- ✅ Verify charts render
- ✅ Test quick action buttons
- ✅ Check recent sales list
- ✅ Try sidebar collapse

### Inventory List
- ✅ Search for products
- ✅ Switch between grid/table views
- ✅ Filter by category and stock
- ✅ Test "Make Sale" modal
- ✅ Click view/edit buttons
- ✅ Check mobile responsiveness

---

## 🔄 Rollback (If Needed)

To go back to the old design:
```bash
# Restore from backup
cp templates_backup/base.html templates/
cp templates_backup/dashboard.html templates/inventory/
cp templates_backup/inventory_list.html templates/inventory/

# Restart server
python manage.py runserver
```

---

## 💡 Tips

1. **Clear Browser Cache** - Press Ctrl+Shift+R to see changes
2. **Test on Mobile** - Use browser dev tools (F12) → Device toolbar
3. **Check Console** - Look for any JavaScript errors (F12)
4. **Try All Features** - Make a test sale, add a product, etc.

---

## 📱 Mobile Testing

Open Chrome DevTools (F12) and test these sizes:
- Mobile: 375px width
- Tablet: 768px width  
- Desktop: 1440px width

---

## ✅ Success Checklist

- [ ] Server runs without errors
- [ ] Dashboard loads with metrics
- [ ] Charts render correctly
- [ ] Sidebar opens and closes
- [ ] Search works
- [ ] Filters work
- [ ] Grid/Table toggle works
- [ ] Modals open and close
- [ ] All buttons are clickable
- [ ] Mobile menu works
- [ ] Looks good on mobile

---

## 🆘 Troubleshooting

### Charts Not Showing?
- Check browser console (F12)
- Verify ApexCharts CDN loaded
- Ensure data is in correct format

### Styles Look Wrong?
- Hard refresh: Ctrl+Shift+R
- Clear browser cache
- Check Tailwind CDN loaded

### Sidebar Not Working?
- Check Alpine.js CDN loaded
- Look for JavaScript errors in console

### Modal Not Opening?
- Verify Alpine.js is loaded
- Check console for errors

---

## 🎉 You're Done!

If everything works, you now have a modern, React-like UI for your Django IMS!

**Next:** Read `IMPROVEMENTS_SUMMARY.md` for full feature list and `MODERNIZATION_GUIDE.md` for customization options.
