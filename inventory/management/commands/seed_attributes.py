"""
Management command to seed common attribute types and values for product variants.
Run: python manage.py seed_attributes
"""

from django.core.management.base import BaseCommand
from inventory.models import AttributeType, AttributeValue


class Command(BaseCommand):
    help = 'Seed common attribute types and values for product variants (Size, Color, etc.)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Clear existing attributes before seeding',
        )

    def handle(self, *args, **options):
        if options['clear']:
            self.stdout.write('Clearing existing attributes...')
            AttributeValue.objects.all().delete()
            AttributeType.objects.all().delete()

        self.stdout.write('Seeding attribute types and values...')

        # ==================== SIZE ATTRIBUTES ====================
        size_type, created = AttributeType.objects.get_or_create(
            name='Size',
            defaults={
                'display_name': 'Size',
                'display_order': 1,
                'is_active': True
            }
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f'  Created attribute type: {size_type.name}'))
        else:
            self.stdout.write(f'  Attribute type already exists: {size_type.name}')

        # Clothing sizes (letter)
        clothing_sizes = [
            ('XS', 'XS', 1),
            ('S', 'S', 2),
            ('M', 'M', 3),
            ('L', 'L', 4),
            ('XL', 'XL', 5),
            ('XXL', 'XXL', 6),
            ('XXXL', '3XL', 7),
        ]

        for value, display, order in clothing_sizes:
            obj, created = AttributeValue.objects.get_or_create(
                attribute_type=size_type,
                value=value,
                defaults={
                    'display_value': display,
                    'display_order': order,
                    'is_active': True
                }
            )
            if created:
                self.stdout.write(f'    + Size: {value}')

        # Shoe sizes (numeric)
        shoe_sizes = [
            ('36', '36', 10),
            ('37', '37', 11),
            ('38', '38', 12),
            ('39', '39', 13),
            ('40', '40', 14),
            ('41', '41', 15),
            ('42', '42', 16),
            ('43', '43', 17),
            ('44', '44', 18),
            ('45', '45', 19),
            ('46', '46', 20),
        ]

        for value, display, order in shoe_sizes:
            obj, created = AttributeValue.objects.get_or_create(
                attribute_type=size_type,
                value=value,
                defaults={
                    'display_value': display,
                    'display_order': order,
                    'is_active': True
                }
            )
            if created:
                self.stdout.write(f'    + Size: {value}')

        # ==================== COLOR ATTRIBUTES ====================
        color_type, created = AttributeType.objects.get_or_create(
            name='Color',
            defaults={
                'display_name': 'Color',
                'display_order': 2,
                'is_active': True
            }
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f'  Created attribute type: {color_type.name}'))
        else:
            self.stdout.write(f'  Attribute type already exists: {color_type.name}')

        colors = [
            ('Black', 'Black', '#000000', 1),
            ('White', 'White', '#FFFFFF', 2),
            ('Grey', 'Grey', '#808080', 3),
            ('Navy', 'Navy', '#000080', 4),
            ('Red', 'Red', '#FF0000', 5),
            ('Blue', 'Blue', '#0000FF', 6),
            ('Green', 'Green', '#008000', 7),
            ('Yellow', 'Yellow', '#FFFF00', 8),
            ('Orange', 'Orange', '#FFA500', 9),
            ('Pink', 'Pink', '#FFC0CB', 10),
            ('Purple', 'Purple', '#800080', 11),
            ('Brown', 'Brown', '#8B4513', 12),
            ('Beige', 'Beige', '#F5F5DC', 13),
            ('Khaki', 'Khaki', '#C3B091', 14),
            ('Maroon', 'Maroon', '#800000', 15),
        ]

        for value, display, color_code, order in colors:
            obj, created = AttributeValue.objects.get_or_create(
                attribute_type=color_type,
                value=value,
                defaults={
                    'display_value': display,
                    'color_code': color_code,
                    'display_order': order,
                    'is_active': True
                }
            )
            if created:
                self.stdout.write(f'    + Color: {value} ({color_code})')

        # ==================== MATERIAL ATTRIBUTES ====================
        material_type, created = AttributeType.objects.get_or_create(
            name='Material',
            defaults={
                'display_name': 'Material',
                'display_order': 3,
                'is_active': True
            }
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f'  Created attribute type: {material_type.name}'))
        else:
            self.stdout.write(f'  Attribute type already exists: {material_type.name}')

        materials = [
            ('Cotton', 'Cotton', 1),
            ('Polyester', 'Polyester', 2),
            ('Wool', 'Wool', 3),
            ('Silk', 'Silk', 4),
            ('Linen', 'Linen', 5),
            ('Denim', 'Denim', 6),
            ('Leather', 'Leather', 7),
            ('Suede', 'Suede', 8),
            ('Canvas', 'Canvas', 9),
            ('Nylon', 'Nylon', 10),
        ]

        for value, display, order in materials:
            obj, created = AttributeValue.objects.get_or_create(
                attribute_type=material_type,
                value=value,
                defaults={
                    'display_value': display,
                    'display_order': order,
                    'is_active': True
                }
            )
            if created:
                self.stdout.write(f'    + Material: {value}')

        # Print summary
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('=' * 50))
        self.stdout.write(self.style.SUCCESS('Attribute seeding complete!'))
        self.stdout.write(f'  Attribute Types: {AttributeType.objects.count()}')
        self.stdout.write(f'  Attribute Values: {AttributeValue.objects.count()}')
        self.stdout.write(self.style.SUCCESS('=' * 50))
