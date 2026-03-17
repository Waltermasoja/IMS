"""
Bulk Import Utilities for Import Orders
Handles CSV uploads for creating multiple products at once
"""

import csv
import io
from decimal import Decimal, InvalidOperation
from django.core.exceptions import ValidationError
from .models import Inventory, Inventory_category, ImportOrderItem


def parse_csv_for_import(csv_file, import_order):
    """
    Parse CSV file and create ImportOrderItems
    
    Expected CSV format:
    product_name,category,quantity,unit_cost,description,label,size,weight,markup_percentage
    
    Returns: (success_count, error_list)
    """
    
    success_count = 0
    errors = []
    
    try:
        # Read CSV file
        decoded_file = csv_file.read().decode('utf-8')
        csv_reader = csv.DictReader(io.StringIO(decoded_file))
        
        required_fields = ['product_name', 'quantity', 'unit_cost']
        
        for row_num, row in enumerate(csv_reader, start=2):  # Start at 2 (1 is header)
            try:
                # Validate required fields
                missing_fields = [field for field in required_fields if not row.get(field, '').strip()]
                if missing_fields:
                    errors.append(f"Row {row_num}: Missing required fields: {', '.join(missing_fields)}")
                    continue
                
                # Get or create category
                category = None
                category_name = row.get('category', '').strip()
                if category_name:
                    category, _ = Inventory_category.objects.get_or_create(
                        name=category_name,
                        defaults={'description': f'Auto-created from import'}
                    )
                
                # Parse numeric fields
                try:
                    quantity = int(row['quantity'])
                    unit_cost = Decimal(row['unit_cost'])
                    weight = Decimal(row.get('weight', '0') or '0')
                    markup_percentage = Decimal(row.get('markup_percentage', '0') or '0')
                except (ValueError, InvalidOperation) as e:
                    errors.append(f"Row {row_num}: Invalid numeric value - {str(e)}")
                    continue
                
                # Create ImportOrderItem
                ImportOrderItem.objects.create(
                    import_order=import_order,
                    is_new_product=True,
                    product_name=row['product_name'].strip(),
                    product_category=category,
                    product_description=row.get('description', '').strip(),
                    product_label=row.get('label', '').strip() or row['product_name'].strip()[:50],
                    product_size=row.get('size', '').strip() or '0',
                    product_weight=weight,
                    quantity=quantity,
                    unit_cost=unit_cost,
                    markup_percentage=markup_percentage if markup_percentage > 0 else None
                )
                
                success_count += 1
                
            except Exception as e:
                errors.append(f"Row {row_num}: Error creating item - {str(e)}")
                continue
        
    except UnicodeDecodeError:
        errors.append("File encoding error. Please ensure the file is UTF-8 encoded.")
    except csv.Error as e:
        errors.append(f"CSV parsing error: {str(e)}")
    except Exception as e:
        errors.append(f"Unexpected error: {str(e)}")
    
    return success_count, errors


def generate_csv_template():
    """
    Generate a CSV template file for bulk import
    Returns CSV content as string
    """
    
    template_data = [
        ['product_name', 'category', 'quantity', 'unit_cost', 'description', 'label', 'size', 'weight', 'markup_percentage'],
        ['Red T-Shirt', 'Clothing', '100', '5.50', 'Cotton red t-shirt', 'RED-TSHIRT', 'M', '0.2', '50'],
        ['Blue Jeans', 'Clothing', '50', '12.00', 'Denim blue jeans', 'BLUE-JEANS', 'L', '0.5', '45'],
        ['Sports Shoes', 'Footwear', '30', '25.00', 'Running sports shoes', 'SPORTS-SHOE', '42', '0.8', '60']
    ]
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerows(template_data)
    
    return output.getvalue()


def validate_csv_file(csv_file):
    """
    Validate CSV file before processing
    Returns: (is_valid, error_message)
    """
    
    # Check file size (max 5MB)
    if csv_file.size > 5 * 1024 * 1024:
        return False, "File size exceeds 5MB limit"
    
    # Check file extension
    if not csv_file.name.lower().endswith('.csv'):
        return False, "File must be a CSV file"
    
    try:
        # Try to read first few lines
        decoded_file = csv_file.read(1024).decode('utf-8')
        csv_file.seek(0)  # Reset file pointer
        
        # Check if it looks like CSV
        if ',' not in decoded_file and '\t' not in decoded_file:
            return False, "File doesn't appear to be a valid CSV"
        
    except UnicodeDecodeError:
        return False, "File encoding error. Please use UTF-8 encoding"
    except Exception as e:
        return False, f"File validation error: {str(e)}"
    
    return True, ""


def bulk_create_products_from_items(import_order):
    """
    Create all inventory items for new products in an import order
    Useful for batch creating products before receiving goods
    
    Returns: (created_count, error_list)
    """
    
    created_count = 0
    errors = []
    
    items = import_order.items.filter(is_new_product=True, inventory_item__isnull=True)
    
    for item in items:
        try:
            item.create_inventory_item()
            created_count += 1
        except Exception as e:
            errors.append(f"{item.product_name}: {str(e)}")
    
    return created_count, errors
