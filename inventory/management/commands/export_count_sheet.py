"""
Export a physical stocktake count sheet for one shop.

Generates a CSV with one row per countable item (each variant of a variant
product; the product itself otherwise), pre-filled with the SYSTEM quantity
and the current selling price. Shop staff fill in `counted_qty` (what is
physically on the shelf) and, where `needs_price` says YES, a
`new_selling_price`. The filled sheet is then applied with:

    python manage.py apply_stocktake --file <filled.csv> --shop-code CLO [...]

USAGE
-----
    python manage.py export_count_sheet --shop-code CLO \
        [--out media/exports/count_sheet_CLO.csv] [--only-unpriced]
"""
import csv
from datetime import date
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from inventory.models import Inventory, Shop, ShopStock


class Command(BaseCommand):
    help = 'Export a stocktake count sheet (CSV) for a shop.'

    def add_arguments(self, parser):
        parser.add_argument('--shop-code', required=True)
        parser.add_argument('--out', default=None,
                            help='Output path. Default: media/exports/count_sheet_{SHOP}_{date}.csv')
        parser.add_argument('--only-unpriced', action='store_true',
                            help='Only rows whose selling price is missing/zero.')
        parser.add_argument('--suspect-cost-above', type=float, default=500,
                            help='Flag needs_cost=YES for unpriced items whose unit cost '
                                 'exceeds this (catches lot totals stored as unit costs).')

    def handle(self, *args, **options):
        try:
            shop = Shop.objects.get(code=options['shop_code'].upper())
        except Shop.DoesNotExist as exc:
            raise CommandError(f"Shop '{options['shop_code']}' not found.") from exc

        out_path = options['out']
        if not out_path:
            exports_dir = Path(settings.MEDIA_ROOT or 'media') / 'exports'
            exports_dir.mkdir(parents=True, exist_ok=True)
            out_path = exports_dir / f'count_sheet_{shop.code}_{date.today().isoformat()}.csv'
        out_path = Path(out_path)

        # Pre-load this shop's stock into a lookup so the sheet reflects
        # per-shop quantities (falling back to the legacy fields the same way
        # ShopStock.get_or_create_for would seed them).
        stock = {
            (ss.inventory_item_id, ss.variant_id): ss.quantity
            for ss in ShopStock.objects.filter(shop=shop)
        }

        def shop_qty(inv, variant=None):
            key = (inv.id, variant.id if variant else None)
            if key in stock:
                return stock[key]
            return variant.quantity_in_stock if variant else inv.quantity_in_Stock

        from decimal import Decimal
        suspect_bound = Decimal(str(options['suspect_cost_above']))

        def flags(cost, price):
            """needs_price / needs_cost markers for the staff filling the sheet.

            A cost is 'suspect' when it's missing, zero, HIGHER than the
            selling price, or (for unpriced items) above --suspect-cost-above —
            the imported workbook stored lot totals as unit costs on many rows,
            so these must be corrected on the sheet or the item is excluded
            from the opening stock valuation.
            """
            needs_price = bool(not price or price <= 0)
            needs_cost = bool(
                cost is None or cost <= 0
                or (price is not None and price > 0 and cost > price)
                or (needs_price and cost is not None and cost > suspect_bound)
            )
            return needs_price, needs_cost

        rows_written = 0
        unpriced = 0
        uncosted = 0
        with out_path.open('w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                'product_code', 'sku', 'product_name', 'label', 'size', 'category',
                'system_qty', 'counted_qty',
                'current_selling_price', 'new_selling_price', 'needs_price',
                'current_unit_cost', 'new_unit_cost', 'needs_cost',
                'notes',
            ])

            qs = (Inventory.objects.all()
                  .select_related('category')
                  .prefetch_related('variants__attribute_values')
                  .order_by('category__name', 'label', 'name'))

            def emit(inv, var, size_label, qty, note=''):
                nonlocal rows_written, unpriced, uncosted
                price = (var.selling_price if var and var.selling_price is not None
                         else inv.selling_price)
                cost = (var.purchase_price if var and var.purchase_price is not None
                        else inv.purchase_price)
                needs_price, needs_cost = flags(cost, price)
                if options['only_unpriced'] and not needs_price:
                    return
                writer.writerow([
                    inv.product_code, var.sku if var else '', inv.name, inv.label or '',
                    size_label, inv.category.name if inv.category else '',
                    qty, '',
                    price if price is not None else '', '', 'YES' if needs_price else '',
                    cost if cost is not None else '', '', 'YES' if needs_cost else '',
                    note,
                ])
                rows_written += 1
                unpriced += int(needs_price)
                uncosted += int(needs_cost)

            for inv in qs:
                if inv.product_code == 'LAYBY-PLACEHOLDER':
                    continue
                variants = [v for v in inv.variants.all() if v.is_active] if inv.has_variants else []
                if variants:
                    for var in variants:
                        size = ' / '.join(av.value for av in var.attribute_values.all()) or ''
                        emit(inv, var, size, shop_qty(inv, var))
                    parent_q = shop_qty(inv)
                    if parent_q and not options['only_unpriced']:
                        emit(inv, None, '(unsized)', parent_q,
                             note='loose/unsized stock on parent product')
                else:
                    emit(inv, None, inv.size or '', shop_qty(inv))

        self.stdout.write(f'Count sheet: {out_path}')
        self.stdout.write(f'  rows: {rows_written}   needing a price: {unpriced}   needing a cost: {uncosted}')
        self.stdout.write('Fill counted_qty, new_selling_price where needs_price=YES, and')
        self.stdout.write('new_unit_cost where needs_cost=YES. Then run:')
        self.stdout.write(f'  python manage.py apply_stocktake --file "{out_path}" '
                          f'--shop-code {shop.code} --opening')
