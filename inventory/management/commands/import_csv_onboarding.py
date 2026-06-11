"""
Generic CSV client-onboarding importer (Django management command).

Imports a new shop's opening data from flat CSV files — the clean-template
path for shops that don't have an ExoticBlossom-style historical workbook
(e.g. Baby Bazaar's go-live). Templates + column docs live in
data/imports/templates/.

USAGE
-----

    python manage.py import_csv_onboarding \
        --dir data/imports/babybazaar/ \
        --shop-code BBY \
        --as-of 2026-07-01 \
        [--skip-stock-je] \
        [--commit]

Expected files in --dir (suppliers/expenses optional):
    products.csv           required
    customers_credit.csv   optional
    open_layby.csv         optional
    suppliers.csv          optional
    expenses.csv           optional

Without --commit the run is a dry-run: all DB writes roll back, but the
audit pack (media/imports/{ts}/) is still written for review.

OPENING BALANCES POSTED
-----------------------
- products.csv     → Inventory/ProductVariant/ShopStock + ONE JE:
                     Dr 1300 Inventory, Cr 3000 Owner's Equity at cost
                     (suppress with --skip-stock-je)
- customers_credit → Customer + opening ARInvoice + JE per customer:
                     Dr 1200 AR, Cr 3100 Retained Earnings
- open_layby       → LaybyPlan with amount_paid set; NO JE (mirrors the
                     ExoticBlossom decision — accountant posts one manual
                     opening JE for unearned revenue if required)
- expenses.csv     → Expense rows (auto-post their own JEs + cashbook)
"""
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils.dateparse import parse_date

from accounting.models import Expense, GLAccount, JournalEntry, JournalLine, LaybyItem, LaybyPlan
from accounting.utils import MissingGLAccountError, require_gl
from inventory.importers import audit
from inventory.importers.ar import _create_opening_ar_invoice, _post_opening_ar_je
from inventory.importers.cashbook import CATEGORY_MAP, INVENTORY_PURCHASE, _match_category, _NO_MATCH
from inventory.importers.csv_loaders import (
    load_customers_credit_csv, load_expenses_csv, load_open_layby_csv,
    load_products_csv, load_suppliers_csv,
)
from inventory.importers.dry_run import DryRunRollback, ImportAborted, transactional_run, update_dates
from inventory.importers.layby import _get_or_create_customer, _get_or_create_placeholder
from inventory.importers.products import _make_prefix, _make_product_code, _slugify
from inventory.models import (
    AttributeType, AttributeValue, Customer, Inventory, Inventory_category,
    ProductVariant, Shop, ShopStock, Supplier,
)

User = get_user_model()

LOG = '[IMPORT-CSV]'
REQUIRED_GL_CODES = ['1200', '1300', '3000', '3100', '6000', '6100', '6200',
                     '6300', '6400', '6900']
VALID_EXPENSE_CATEGORIES = {'RENT', 'UTILITIES', 'WAGES', 'FREIGHT', 'MARKETING', 'OTHER'}
# Default GL per category when only category_override is given.
CATEGORY_DEFAULT_GL = {
    'RENT': '6000', 'UTILITIES': '6100', 'WAGES': '6200',
    'FREIGHT': '6300', 'MARKETING': '6400', 'OTHER': '6900',
}


class Command(BaseCommand):
    help = 'Onboard a new shop from flat CSV templates (dry-run by default).'

    def add_arguments(self, parser):
        parser.add_argument('--dir', required=True,
                            help='Directory containing the CSV files.')
        parser.add_argument('--shop-code', required=True,
                            help="Shop code (e.g. 'BBY') this data belongs to.")
        parser.add_argument('--as-of', default=None,
                            help='Opening-balance date (YYYY-MM-DD). Default: today.')
        parser.add_argument('--skip-stock-je', action='store_true',
                            help='Do not post the opening-inventory journal entry.')
        parser.add_argument('--force', action='store_true',
                            help='Proceed even if the shop already has ShopStock rows.')
        parser.add_argument('--commit', action='store_true',
                            help='Commit DB changes. Without this flag the run rolls back.')

    # ------------------------------------------------------------------

    def handle(self, *args, **options):
        src = Path(options['dir'])
        if not src.is_dir():
            raise CommandError(f'Not a directory: {src}')
        products_path = src / 'products.csv'
        if not products_path.is_file():
            raise CommandError(f'products.csv is required but missing in {src}')

        as_of = parse_date(options['as_of']) if options['as_of'] else datetime.utcnow().date()
        if as_of is None:
            raise CommandError('--as-of must be YYYY-MM-DD.')

        # Pre-flight: shop, GL accounts, attribute seed, placeholder user
        try:
            shop = Shop.objects.get(code=options['shop_code'].upper())
        except Shop.DoesNotExist as exc:
            raise CommandError(
                f"Shop '{options['shop_code']}' not found. Run: python manage.py create_initial_shops"
            ) from exc
        try:
            for code in REQUIRED_GL_CODES:
                require_gl(code)
        except MissingGLAccountError as exc:
            raise CommandError(f'{exc}\nRun: python manage.py init_gl_accounts') from exc
        try:
            size_type = AttributeType.objects.get(name='Size')
        except AttributeType.DoesNotExist as exc:
            raise CommandError("AttributeType 'Size' missing. Run: python manage.py seed_attributes") from exc
        try:
            recorded_by = User.objects.get(username='imported_history')
        except User.DoesNotExist as exc:
            raise CommandError(
                "User 'imported_history' missing. Run: python manage.py seed_imported_history_user"
            ) from exc

        # Shop-scoped empty check (a global --require-empty is meaningless when
        # another shop's data is already live).
        existing_stock = ShopStock.objects.filter(shop=shop).count()
        if existing_stock and not options['force']:
            raise CommandError(
                f"Shop {shop.code} already has {existing_stock} ShopStock rows — "
                f"this looks like a re-run. Use --force to override."
            )

        out_dir = audit.make_run_dir(datetime.utcnow())
        log = lambda msg: (self.stdout.write(msg), self.stdout.flush())

        log(f'{LOG} Source dir : {src}')
        log(f'{LOG} Shop       : {shop.code} ({shop.name})')
        log(f'{LOG} As-of date : {as_of}')
        log(f'{LOG} Mode       : {"COMMIT" if options["commit"] else "DRY-RUN"}')
        log(f'{LOG} Audit dir  : {out_dir}')
        log('')

        counts: dict = {}
        errors: list[dict] = []

        try:
            with transactional_run(commit=options['commit'], log=log):
                self._suppliers(src, counts, errors, log)
                self._products(products_path, shop, size_type, as_of,
                               options['skip_stock_je'], counts, errors, log)
                self._customers(src, shop, as_of, counts, errors, log)
                self._layby(src, shop, counts, errors, log)
                self._expenses(src, shop, recorded_by, counts, errors, log)

                log(f'{LOG} Emitting in-transaction audit CSVs…')
                audit.write_trial_balance(out_dir)
                audit.write_ar_aging(out_dir, as_of=as_of)
        except ImportAborted as exc:
            errors.append({'file': '', 'row': 0, 'field': '', 'problem': str(exc), 'raw': ''})
            self._emit(out_dir, src, shop, as_of, options['commit'], counts, errors)
            raise CommandError(str(exc)) from exc
        except DryRunRollback:
            pass

        self._emit(out_dir, src, shop, as_of, options['commit'], counts, errors)
        log('')
        log(f'{LOG} Done. {len(errors)} row error(s) — see import_errors.csv. Audit pack: {out_dir}')
        if not options['commit']:
            log(f'{LOG} Reminder: DRY-RUN — re-run with --commit to persist.')

    # ------------------------------------------------------------------
    # Phases
    # ------------------------------------------------------------------

    def _suppliers(self, src, counts, errors, log):
        path = src / 'suppliers.csv'
        if not path.is_file():
            return
        rows, errs = load_suppliers_csv(path)
        errors.extend(errs)
        created = 0
        for r in rows:
            _, was_created = Supplier.objects.get_or_create(
                name__iexact=r['name'],
                defaults={
                    'name': r['name'], 'contact_person': r['contact_person'],
                    'phone': r['phone'], 'email': r['email'], 'country': r['country'],
                },
            )
            created += int(was_created)
        counts['suppliers_created'] = created
        log(f'{LOG} suppliers: {created} created, {len(rows) - created} already existed')

    def _products(self, path, shop, size_type, as_of, skip_stock_je, counts, errors, log):
        rows, errs = load_products_csv(path)
        errors.extend(errs)

        # Group rows: one Inventory per (label, product_name); rows with a
        # size value become ProductVariants of that Inventory.
        groups: dict[tuple, list[dict]] = {}
        for r in rows:
            groups.setdefault((r['label'], r['product_name']), []).append(r)

        code_counter: dict[str, int] = {}
        category_cache: dict[str, Inventory_category] = {}
        products_created = variants_created = shopstock_rows = 0
        opening_value = Decimal('0')

        for (label, name), grp in groups.items():
            prefix = _make_prefix(_slugify(label) or 'item', _slugify(name) or 'product')
            seq = code_counter.get(prefix, 0) + 1
            product_code = _make_product_code(prefix, seq)
            while Inventory.objects.filter(product_code=product_code).exists():
                seq += 1
                product_code = _make_product_code(prefix, seq)
            code_counter[prefix] = seq

            sized = [g for g in grp if g['size']]
            unsized = [g for g in grp if not g['size']]
            has_variants = bool(sized)

            cat_name = next((g['category'] for g in grp if g['category']), '')
            category = None
            if cat_name:
                category = category_cache.get(cat_name.lower())
                if category is None:
                    category, _ = Inventory_category.objects.get_or_create(name=cat_name)
                    category_cache[cat_name.lower()] = category

            purchase = next((g['purchase_cost'] for g in grp if g['purchase_cost'] is not None), None)
            selling = next((g['selling_price'] for g in grp if g['selling_price'] is not None), None)
            parent_qty = sum(g['opening_qty'] for g in unsized)

            inv = Inventory.objects.create(
                product_code=product_code,
                name=name,
                label=label or None,
                description=next((g['notes'] for g in grp if g['notes']), '') or name,
                purchase_price=purchase,
                selling_price=selling,
                has_variants=has_variants,
                quantity_in_Stock=parent_qty,
                category=category,
            )
            products_created += 1
            if has_variants:
                inv.variant_attributes.add(size_type)

            if not has_variants or parent_qty > 0:
                ss = ShopStock.get_or_create_for(shop, inv, variant=None)
                ss.quantity = parent_qty
                ss.save(update_fields=['quantity', 'last_updated'])
                shopstock_rows += 1
            if purchase is not None:
                opening_value += purchase * parent_qty

            # Variants — collapse duplicate sizes within the group by summing qty.
            size_qty: dict[str, int] = {}
            size_cost: dict[str, Decimal | None] = {}
            for g in sized:
                size_qty[g['size']] = size_qty.get(g['size'], 0) + g['opening_qty']
                if g['purchase_cost'] is not None:
                    size_cost[g['size']] = g['purchase_cost']
            for size_str, qty in size_qty.items():
                attr_val, _ = AttributeValue.objects.get_or_create(
                    attribute_type=size_type, value=size_str,
                    defaults={'display_value': size_str},
                )
                var = ProductVariant.objects.create(product=inv, quantity_in_stock=qty)
                var.attribute_values.set([attr_val])
                var.sku = var.generate_sku()
                var.barcode = var.sku.upper().replace(' ', '')[:32] or None
                var.save(update_fields=['sku', 'barcode'])
                variants_created += 1

                ss = ShopStock.get_or_create_for(shop, inv, variant=var)
                ss.quantity = qty
                ss.save(update_fields=['quantity', 'last_updated'])
                shopstock_rows += 1

                cost = size_cost.get(size_str, purchase)
                if cost is not None:
                    opening_value += cost * qty

        # One opening-stock JE for the whole file: Dr 1300, Cr 3000.
        if opening_value > 0 and not skip_stock_je:
            je = JournalEntry.objects.create(
                memo=f'Opening inventory — {shop.code} CSV onboarding',
                shop=shop,
            )
            update_dates(JournalEntry, je.pk, entry_date=as_of)
            JournalLine.objects.create(entry=je, account=require_gl('1300'),
                                       debit=opening_value, description='Opening stock at cost')
            JournalLine.objects.create(entry=je, account=require_gl('3000'),
                                       credit=opening_value, description='Opening equity — stock')
            je.assert_balanced()
            counts['opening_stock_je_value'] = opening_value

        counts['products_created'] = products_created
        counts['variants_created'] = variants_created
        counts['shopstock_rows'] = shopstock_rows
        log(f'{LOG} products: {products_created} products + {variants_created} variants '
            f'from {len(rows)} rows (opening value ${opening_value})')

    def _customers(self, src, shop, as_of, counts, errors, log):
        path = src / 'customers_credit.csv'
        if not path.is_file():
            return
        rows, errs = load_customers_credit_csv(path)
        errors.extend(errs)

        ar_acct = require_gl('1200')
        re_acct = require_gl('3100')
        ctx_shim = SimpleNamespace(shop=shop)

        created = 0
        for r in rows:
            cust = Customer.objects.filter(name__iexact=r['customer_name']).first()
            if cust:
                cust.current_balance += r['balance']
                cust.save(update_fields=['current_balance'])
            else:
                cust = Customer.objects.create(
                    name=r['customer_name'],
                    status='ACTIVE',
                    credit_limit=r['credit_limit'],
                    current_balance=r['balance'],
                    phone=r['contact'][:50] if r['contact'] else '',
                )
            _create_opening_ar_invoice(cust, r['balance'], r['earliest_invoice_date'], ctx_shim)
            _post_opening_ar_je(cust, r['balance'], ar_acct, re_acct, ctx_shim,
                                as_of_date=r['earliest_invoice_date'])
            created += 1

        counts['ar_customers'] = created
        log(f'{LOG} customers: {created} opening AR balance(s) posted')

    def _layby(self, src, shop, counts, errors, log):
        path = src / 'open_layby.csv'
        if not path.is_file():
            return
        rows, errs = load_open_layby_csv(path)
        errors.extend(errs)

        placeholder = _get_or_create_placeholder(shop)
        created = 0
        for r in rows:
            customer, _ = _get_or_create_customer(r['customer_name'])
            from datetime import timedelta
            plan = LaybyPlan.objects.create(
                customer=customer,
                shop=shop,
                status='ACTIVE',
                deposit_amount=r['deposit'],
                total_price=r['total_price'],
                amount_paid=r['total_price'] - r['balance'],
                due_date=r['purchase_date'] + timedelta(days=90),
            )
            update_dates(LaybyPlan, plan.pk, created_date=r['purchase_date'])
            LaybyItem.objects.create(
                plan=plan, inventory_item=placeholder, quantity=1,
                unit_price=r['total_price'],
            )
            created += 1

        counts['layby_plans'] = created
        log(f'{LOG} layby: {created} active plan(s) created')

    def _expenses(self, src, shop, recorded_by, counts, errors, log):
        path = src / 'expenses.csv'
        if not path.is_file():
            return
        rows, errs = load_expenses_csv(path)
        errors.extend(errs)

        created = skipped = 0
        for r in rows:
            override = r['category_override']
            if override:
                if override not in VALID_EXPENSE_CATEGORIES:
                    errors.append({'file': path.name, 'row': r['row'], 'field': 'category_override',
                                   'problem': f'unknown category {override!r}', 'raw': r['description']})
                    skipped += 1
                    continue
                category, gl_code = override, CATEGORY_DEFAULT_GL[override]
            else:
                mapping = _match_category(r['description'])
                if mapping is _NO_MATCH or mapping is None:
                    errors.append({'file': path.name, 'row': r['row'], 'field': 'description',
                                   'problem': 'no category match — add category_override',
                                   'raw': r['description']})
                    skipped += 1
                    continue
                category, gl_code = mapping
                if category == INVENTORY_PURCHASE or gl_code not in CATEGORY_DEFAULT_GL.values():
                    errors.append({'file': path.name, 'row': r['row'], 'field': 'description',
                                   'problem': 'maps to a non-expense account — record manually',
                                   'raw': r['description']})
                    skipped += 1
                    continue

            Expense.objects.create(
                date=r['date'],
                category=category,
                description=r['description'],
                amount=r['amount'],
                vat_amount=Decimal('0'),
                gl_account=GLAccount.objects.get(code=gl_code),
                payment_method='CASH',
                shop=shop,
                recorded_by=recorded_by,
            )
            created += 1

        counts['expenses_created'] = created
        counts['expenses_skipped'] = skipped
        log(f'{LOG} expenses: {created} created, {skipped} skipped (see import_errors.csv)')

    # ------------------------------------------------------------------

    def _emit(self, out_dir, src, shop, as_of, commit, counts, errors):
        import csv as _csv
        with (out_dir / 'import_errors.csv').open('w', newline='', encoding='utf-8') as f:
            w = _csv.DictWriter(f, fieldnames=['file', 'row', 'field', 'problem', 'raw'])
            w.writeheader()
            w.writerows(errors)
        audit.write_summary_text(out_dir, {
            'workbook': str(src),
            'shop_code': shop.code,
            'cutoff': as_of.isoformat(),
            'ar_cutoff': as_of.isoformat(),
            'commit': commit,
            'counts': {k: str(v) for k, v in counts.items()},
            'errors': [f"{e['file']}:{e['row']} {e['problem']}" for e in errors[:50]],
        })
