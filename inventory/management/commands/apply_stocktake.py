"""
Apply a filled stocktake count sheet (from export_count_sheet).

For every row with a `counted_qty`, the shop's stock is corrected to the
counted number (ShopStock + the legacy quantity fields the POS reads), and a
StockMovement records the adjustment. Rows with a `new_selling_price` update
pricing: parent-level when every variant of the product gets the same price,
per-variant overrides otherwise.

ACCOUNTING
----------
--opening   First stocktake after a data migration: posts ONE journal entry
            that corrects GL 1300 Inventory to the counted value at cost
            (Dr/Cr 1300 vs 3000 Owner's Equity). Use this for the CLO
            post-import stocktake, where 1300 currently shows COGS without
            any opening stock value.
(default)   Routine stocktake: net shrinkage posts Dr 5100 Inventory Loss /
            Cr 1300; net overage posts the reverse.

USAGE
-----
    python manage.py apply_stocktake \
        --file media/exports/count_sheet_CLO_2026-06-12.csv \
        --shop-code CLO --opening [--as-of 2026-06-12] [--commit]

Dry-run by default; audit pack written to media/imports/{ts}/ either way.
"""
import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Sum
from django.utils.dateparse import parse_date

from accounting.models import JournalEntry, JournalLine
from accounting.utils import MissingGLAccountError, require_gl
from inventory.importers import audit
from inventory.importers.dry_run import DryRunRollback, transactional_run, update_dates
from inventory.models import Inventory, ProductVariant, Shop, ShopStock, StockMovement

LOG = '[STOCKTAKE]'


def _dec(value):
    s = (value or '').strip().replace(',', '').replace('$', '')
    if not s:
        return None
    try:
        return Decimal(s).quantize(Decimal('0.01'))
    except InvalidOperation as exc:
        raise ValueError(f'not a number: {value!r}') from exc


def _int(value):
    s = (value or '').strip()
    if not s:
        return None
    try:
        return int(float(s))
    except ValueError as exc:
        raise ValueError(f'not an integer: {value!r}') from exc


class Command(BaseCommand):
    help = 'Apply a filled stocktake count sheet (dry-run by default).'

    def add_arguments(self, parser):
        parser.add_argument('--file', required=True)
        parser.add_argument('--shop-code', required=True)
        parser.add_argument('--as-of', default=None,
                            help='Adjustment date (YYYY-MM-DD). Default: today.')
        parser.add_argument('--opening', action='store_true',
                            help='First-stocktake mode: correct GL 1300 to counted value '
                                 'against 3000 Owner\'s Equity instead of posting shrinkage.')
        parser.add_argument('--commit', action='store_true')

    def handle(self, *args, **options):
        path = Path(options['file'])
        if not path.is_file():
            raise CommandError(f'File not found: {path}')
        try:
            shop = Shop.objects.get(code=options['shop_code'].upper())
        except Shop.DoesNotExist as exc:
            raise CommandError(f"Shop '{options['shop_code']}' not found.") from exc
        as_of = parse_date(options['as_of']) if options['as_of'] else datetime.utcnow().date()
        if as_of is None:
            raise CommandError('--as-of must be YYYY-MM-DD.')
        try:
            inv_acct = require_gl('1300')
            equity_acct = require_gl('3000')
            loss_acct = require_gl('5100')
        except MissingGLAccountError as exc:
            raise CommandError(str(exc)) from exc

        out_dir = audit.make_run_dir(datetime.utcnow())
        log = lambda m: (self.stdout.write(m), self.stdout.flush())
        log(f'{LOG} File    : {path}')
        log(f'{LOG} Shop    : {shop.code} ({shop.name})')
        log(f'{LOG} As-of   : {as_of}')
        log(f'{LOG} Mode    : {"OPENING" if options["opening"] else "ROUTINE"} '
            f'{"COMMIT" if options["commit"] else "DRY-RUN"}')
        log(f'{LOG} Audit   : {out_dir}')

        with path.open(newline='', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            raw_rows = [{(k or '').strip().lower(): (v or '') for k, v in r.items()}
                        for r in reader]

        errors: list[dict] = []
        variances: list[dict] = []
        price_updates: list[dict] = []
        no_cost: list[dict] = []
        counts = {'rows_seen': len(raw_rows)}

        try:
            with transactional_run(commit=options['commit'], log=log):
                self._apply(raw_rows, shop, as_of, options['opening'],
                            inv_acct, equity_acct, loss_acct,
                            errors, variances, price_updates, no_cost, counts, log)
                audit.write_trial_balance(out_dir)
        except DryRunRollback:
            pass

        self._emit(out_dir, path, shop, as_of, options, counts,
                   errors, variances, price_updates, no_cost)
        log(f'{LOG} Done. {len(variances)} quantity change(s), {len(price_updates)} price '
            f'update(s), {len(errors)} error(s). Audit pack: {out_dir}')
        if not options['commit']:
            log(f'{LOG} DRY-RUN — re-run with --commit to persist.')

    # ------------------------------------------------------------------

    def _apply(self, raw_rows, shop, as_of, opening_mode,
               inv_acct, equity_acct, loss_acct,
               errors, variances, price_updates, no_cost, counts, log):
        seen_keys = set()
        shrink_value = Decimal('0')
        overage_value = Decimal('0')
        # Collected price/cost edits, grouped per product for the parent-vs-variant decision.
        pending_prices: dict[int, list[tuple[ProductVariant | None, Decimal]]] = {}
        pending_costs: dict[int, list[tuple[ProductVariant | None, Decimal]]] = {}

        for i, r in enumerate(raw_rows, start=2):
            sku = (r.get('sku') or '').strip()
            pcode = (r.get('product_code') or '').strip()
            if not sku and not pcode:
                continue
            try:
                counted = _int(r.get('counted_qty'))
                new_price = _dec(r.get('new_selling_price'))
                new_cost = _dec(r.get('new_unit_cost'))
            except ValueError as exc:
                errors.append({'row': i, 'sku': sku or pcode, 'problem': str(exc)})
                continue
            if counted is None and new_price is None and new_cost is None:
                continue  # untouched row
            if counted is not None and counted < 0:
                errors.append({'row': i, 'sku': sku or pcode, 'problem': 'negative counted_qty'})
                continue

            variant = None
            if sku:
                variant = (ProductVariant.objects.select_related('product')
                           .filter(sku=sku).first())
                if variant is None:
                    errors.append({'row': i, 'sku': sku, 'problem': 'unknown sku'})
                    continue
                inv = variant.product
            else:
                inv = Inventory.objects.filter(product_code=pcode).first()
                if inv is None:
                    errors.append({'row': i, 'sku': pcode, 'problem': 'unknown product_code'})
                    continue

            key = (inv.id, variant.id if variant else None)
            if key in seen_keys:
                errors.append({'row': i, 'sku': sku or pcode, 'problem': 'duplicate row for this item'})
                continue
            seen_keys.add(key)

            cost = None
            if variant is not None:
                cost = variant.purchase_price if variant.purchase_price is not None else inv.purchase_price
            else:
                cost = inv.purchase_price
            if new_cost is not None:
                if new_cost <= 0:
                    errors.append({'row': i, 'sku': sku or pcode, 'problem': 'new_unit_cost must be > 0'})
                else:
                    pending_costs.setdefault(inv.id, []).append((variant, new_cost))
                    cost = new_cost  # value this row's variance at the corrected cost

            # ── Quantity correction ────────────────────────────────────────
            if counted is not None:
                ss = ShopStock.get_or_create_for(shop, inv, variant=variant)
                system_qty = ss.quantity
                delta = counted - system_qty
                if delta != 0:
                    ss.quantity = counted
                    ss.save(update_fields=['quantity', 'last_updated'])
                    if variant is not None:
                        variant.quantity_in_stock = counted
                        variant.save(update_fields=['quantity_in_stock'])
                    else:
                        inv.quantity_in_Stock = counted
                        inv.save(update_fields=['quantity_in_Stock'])
                    StockMovement.objects.create(
                        inventory_item=inv,
                        movement_type='IN' if delta > 0 else 'OUT',
                        quantity=abs(delta),
                        reason=f'Stocktake {as_of.isoformat()}'
                               + (f' [{variant.sku}]' if variant else ''),
                        shop=shop,
                    )
                    if cost is None:
                        no_cost.append({'sku': sku or pcode, 'name': inv.name,
                                        'delta': delta, 'problem': 'no purchase cost — value variance excluded'})
                    else:
                        value = cost * delta
                        if value < 0:
                            shrink_value += -value
                        else:
                            overage_value += value
                    variances.append({
                        'sku': sku or pcode, 'name': inv.name,
                        'size': (r.get('size') or '').strip(),
                        'system_qty': system_qty, 'counted_qty': counted, 'delta': delta,
                        'unit_cost': cost if cost is not None else '',
                        'value_delta': (cost * delta) if cost is not None else '',
                    })

            # ── Price update (collected; applied per-product below) ────────
            if new_price is not None:
                if new_price <= 0:
                    errors.append({'row': i, 'sku': sku or pcode, 'problem': 'new_selling_price must be > 0'})
                else:
                    pending_prices.setdefault(inv.id, []).append((variant, new_price))

        # Apply price/cost edits: if every edited row of a product carries the
        # same value, set it on the parent (variants inherit); else per-variant.
        def apply_grouped(pending, field, label):
            for inv_id, edits in pending.items():
                inv = Inventory.objects.get(pk=inv_id)
                values = {p for _, p in edits}
                if len(values) == 1 and (len(edits) > 1 or edits[0][0] is None or not inv.has_variants):
                    value = values.pop()
                    old = getattr(inv, field)
                    setattr(inv, field, value)
                    inv.save(update_fields=[field])
                    # Clear stale per-variant overrides so the parent value rules.
                    ProductVariant.objects.filter(product=inv).exclude(
                        **{f'{field}__isnull': True}).update(**{field: None})
                    price_updates.append({'sku': inv.product_code, 'name': inv.name,
                                          'level': f'product {label}', 'old': old, 'new': value})
                else:
                    for variant, value in edits:
                        if variant is None:
                            old = getattr(inv, field)
                            setattr(inv, field, value)
                            inv.save(update_fields=[field])
                            price_updates.append({'sku': inv.product_code, 'name': inv.name,
                                                  'level': f'product {label}', 'old': old, 'new': value})
                        else:
                            old = getattr(variant, field)
                            setattr(variant, field, value)
                            variant.save(update_fields=[field])
                            price_updates.append({'sku': variant.sku, 'name': inv.name,
                                                  'level': f'variant {label}', 'old': old, 'new': value})

        apply_grouped(pending_prices, 'selling_price', 'price')
        apply_grouped(pending_costs, 'purchase_price', 'cost')

        # ── Journal entry ───────────────────────────────────────────────────
        if opening_mode:
            # Correct GL 1300 to the counted value of THIS shop's stock at cost.
            # The imported workbook stored lot totals as unit costs on many
            # rows, so any cost that is missing or exceeds the selling price is
            # SUSPECT: excluded from the valuation and reported for correction
            # via the count sheet's new_unit_cost column.
            target = Decimal('0')
            excluded_value = Decimal('0')
            for ss in (ShopStock.objects.filter(shop=shop)
                       .select_related('inventory_item', 'variant')):
                if ss.quantity <= 0:
                    continue
                inv_item = ss.inventory_item
                if ss.variant is not None:
                    item_cost = (ss.variant.purchase_price
                                 if ss.variant.purchase_price is not None
                                 else inv_item.purchase_price)
                    item_price = (ss.variant.selling_price
                                  if ss.variant.selling_price is not None
                                  else inv_item.selling_price)
                    item_sku = ss.variant.sku
                else:
                    item_cost = inv_item.purchase_price
                    item_price = inv_item.selling_price
                    item_sku = inv_item.product_code
                if not item_cost or item_cost <= 0:
                    no_cost.append({'sku': item_sku, 'name': inv_item.name,
                                    'delta': ss.quantity,
                                    'problem': 'no cost — excluded from opening valuation'})
                    continue
                if not item_price or item_price <= 0:
                    # Unpriced → the cost cannot be sanity-checked; exclude
                    # until the item is priced via new_selling_price.
                    excluded_value += item_cost * ss.quantity
                    no_cost.append({'sku': item_sku, 'name': inv_item.name,
                                    'delta': ss.quantity,
                                    'problem': 'no selling price — excluded; set new_selling_price'})
                    continue
                if item_cost > item_price:
                    excluded_value += item_cost * ss.quantity
                    no_cost.append({'sku': item_sku, 'name': inv_item.name,
                                    'delta': ss.quantity,
                                    'problem': f'suspect cost {item_cost} > price {item_price} '
                                               f'— excluded; fix via new_unit_cost'})
                    continue
                target += item_cost * ss.quantity
            counts['suspect_cost_value_excluded'] = excluded_value
            current = JournalLine.objects.filter(account=inv_acct).aggregate(
                d=Sum('debit'), c=Sum('credit'))
            current_bal = (current['d'] or Decimal('0')) - (current['c'] or Decimal('0'))
            adjustment = (target - current_bal).quantize(Decimal('0.01'))
            counts['gl_1300_target'] = target
            counts['gl_1300_before'] = current_bal
            counts['gl_1300_adjustment'] = adjustment
            if adjustment != 0:
                je = JournalEntry.objects.create(
                    memo=f'Opening inventory correction per stocktake {as_of} — {shop.code}',
                    shop=shop,
                )
                update_dates(JournalEntry, je.pk, entry_date=as_of)
                if adjustment > 0:
                    JournalLine.objects.create(entry=je, account=inv_acct, debit=adjustment,
                                               description='Stock on hand at cost (stocktake)')
                    JournalLine.objects.create(entry=je, account=equity_acct, credit=adjustment,
                                               description='Opening equity correction')
                else:
                    JournalLine.objects.create(entry=je, account=equity_acct, debit=-adjustment,
                                               description='Opening equity correction')
                    JournalLine.objects.create(entry=je, account=inv_acct, credit=-adjustment,
                                               description='Stock on hand at cost (stocktake)')
                je.assert_balanced()
        else:
            counts['shrinkage_value'] = shrink_value
            counts['overage_value'] = overage_value
            if shrink_value or overage_value:
                je = JournalEntry.objects.create(
                    memo=f'Stocktake adjustment {as_of} — {shop.code}',
                    shop=shop,
                )
                update_dates(JournalEntry, je.pk, entry_date=as_of)
                if shrink_value:
                    JournalLine.objects.create(entry=je, account=loss_acct, debit=shrink_value,
                                               description='Stocktake shrinkage at cost')
                    JournalLine.objects.create(entry=je, account=inv_acct, credit=shrink_value,
                                               description='Stocktake shrinkage at cost')
                if overage_value:
                    JournalLine.objects.create(entry=je, account=inv_acct, debit=overage_value,
                                               description='Stocktake overage at cost')
                    JournalLine.objects.create(entry=je, account=loss_acct, credit=overage_value,
                                               description='Stocktake overage at cost')
                je.assert_balanced()

        counts['quantity_changes'] = len(variances)
        counts['price_updates'] = len(price_updates)
        log(f'{LOG} {len(variances)} quantity change(s); shrink ${shrink_value} / over ${overage_value}'
            if not opening_mode else
            f'{LOG} {len(variances)} quantity change(s); 1300 adjustment {counts.get("gl_1300_adjustment", 0)}')

    # ------------------------------------------------------------------

    def _emit(self, out_dir, path, shop, as_of, options, counts,
              errors, variances, price_updates, no_cost):
        def _w(name, fieldnames, rows):
            with (out_dir / name).open('w', newline='', encoding='utf-8') as f:
                w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
                w.writeheader()
                w.writerows(rows)

        _w('stocktake_variances.csv',
           ['sku', 'name', 'size', 'system_qty', 'counted_qty', 'delta', 'unit_cost', 'value_delta'],
           variances)
        _w('stocktake_price_updates.csv', ['sku', 'name', 'level', 'old', 'new'], price_updates)
        _w('stocktake_errors.csv', ['row', 'sku', 'problem'], errors)
        _w('stocktake_no_cost.csv', ['sku', 'name', 'delta', 'problem'], no_cost)
        audit.write_summary_text(out_dir, {
            'workbook': str(path),
            'shop_code': shop.code,
            'cutoff': as_of.isoformat(),
            'ar_cutoff': '-',
            'commit': options['commit'],
            'counts': {k: str(v) for k, v in counts.items()},
            'errors': [f"row {e['row']}: {e['problem']}" for e in errors[:50]],
        })
