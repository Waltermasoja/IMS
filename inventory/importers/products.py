"""
Phase 2 — build Inventory, ProductVariant, and opening ShopStock from product sheets.

Exposes one callable: run(ctx: RunContext) -> None.
"""
import re
import unicodedata
from collections import defaultdict

from inventory.importers import LOG_PREFIX
from inventory.importers.context import RunContext
from inventory.importers.dry_run import ImportAborted
from inventory.importers.excel_loader import (
    load_all_product_sheets, load_stock_purchase,
    validate_product_sheet_columns,
)
from inventory.importers.fuzzy import FuzzyMatcher
from inventory.importers.stock_signals import (
    derive_group_quantities, derive_pricing_sanity,
)
from inventory.models import (
    AttributeType, AttributeValue, Inventory, Inventory_category,
    ProductVariant, ShopStock,
)


# Maps the loader's category slug (the value already attached to every row by
# excel_loader.py) to the human-readable Inventory_category.name we want to
# store. The keys MUST match the loader's tags exactly.
_CATEGORY_DISPLAY = {
    'dresses':              'Dresses',
    'jackets_jerseys':      'Jackets & Jerseys',
    'suits':                'Suits',
    'hats_shoes_bags':      'Hats, Shoes & Bags',
    'stock_purchase_2026':  'Other (Stock Purchase 2026)',
}


def _resolve_categories(all_rows: list[dict]) -> dict[str, Inventory_category]:
    """Idempotently seed an Inventory_category row per distinct slug seen
    in the loaded rows; return slug -> Inventory_category lookup map.
    """
    seen_slugs = {r['category'] for r in all_rows if r.get('category')}
    lookup: dict[str, Inventory_category] = {}
    for slug in seen_slugs:
        display = _CATEGORY_DISPLAY.get(slug, slug.replace('_', ' ').title())
        cat, _ = Inventory_category.objects.get_or_create(name=display)
        lookup[slug] = cat
    return lookup


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _slugify(text: str) -> str:
    """Lowercase [a-z0-9]+ joined by '-', trimmed. Non-ASCII normalised via NFKD."""
    normalized = (
        unicodedata.normalize('NFKD', text)
        .encode('ascii', 'ignore')
        .decode('ascii')
    )
    return re.sub(r'[^a-z0-9]+', '-', normalized.lower()).strip('-')


# Inventory.product_code is max_length=20. Inventory.save() derives barcode
# from product_code, so a collision in either becomes a UNIQUE-violation. We
# reserve 5 chars for the "-NNNN" sequence suffix so up to 9999 collisions on
# the same prefix can be disambiguated.
_PRODUCT_CODE_TOTAL = 20
_SEQ_RESERVE = 5  # "-9999"
_PREFIX_BUDGET = _PRODUCT_CODE_TOTAL - _SEQ_RESERVE  # 15 chars for "label-desc"


def _make_prefix(label_slug: str, desc_slug: str) -> str:
    """Build the truncated 'label-desc' prefix that the seq counter is keyed on.

    Two distinct descriptions whose slugs differ only after position 15 still
    collide on this prefix; we rely on the seq suffix to separate them.
    """
    return f"{label_slug or 'item'}-{desc_slug or 'product'}"[:_PREFIX_BUDGET]


def _make_product_code(prefix: str, seq: int) -> str:
    """Build '{prefix}-{seq}' — guaranteed <= 20 chars by construction."""
    return f"{prefix}-{seq}"


def _pick_first(rows: list[dict], *keys: str):
    """Return the first non-None value found by scanning rows for any of keys."""
    for key in keys:
        for row in rows:
            val = row.get(key)
            if val is not None:
                return val
    return None


# ---------------------------------------------------------------------------
# Phase entry point
# ---------------------------------------------------------------------------

def run(ctx: RunContext) -> None:
    """Phase 2 entry point — build product catalogue from ExoticBlossom sheets."""

    # ── Initialise fuzzy matcher if the orchestrator hasn't done it yet ───────
    if ctx.fuzzy_matcher is None:
        ctx.fuzzy_matcher = FuzzyMatcher(threshold=ctx.fuzzy_threshold)

    # ── 1. Load rows from the four category sheets only. Stock purchase 2026
    # is a historical purchase log — its rows overlap with the category sheets
    # and would double-count opening stock if included. Per user decision, we
    # archive those rows to HistoricalRecord (so the data is preserved) but do
    # NOT use them to build Inventory / ShopStock.
    all_rows = load_all_product_sheets(ctx.workbook_path)
    ctx.bump('product_rows_seen', len(all_rows))

    # Archive stock_purchase_2026 separately for the operator's audit trail.
    from inventory.importers.historical import archive_row
    sp_rows = load_stock_purchase(ctx.workbook_path)
    for sp in sp_rows:
        archive_row(
            sheet_name='stock purchase 2026',
            row_index=sp['row_index'],
            row_data=sp,
            record_date=sp.get('purchase_date'),
            shop=ctx.shop,
            source_workbook=ctx.source_workbook,
            counter=ctx.historical_counter,
        )
    ctx.bump('stock_purchase_archived', len(sp_rows))

    # ── 2. Resolve Size AttributeType — must exist via seed_attributes ─────────
    try:
        size_type = AttributeType.objects.get(name='Size')
    except AttributeType.DoesNotExist:
        raise ImportAborted(
            f"{LOG_PREFIX} AttributeType 'Size' not found — "
            "run: python manage.py seed_attributes"
        )

    # ── 2b. Seed Inventory_category rows from per-row category tags ────────────
    # Loader attaches a 'category' slug (e.g. 'dresses', 'suits') to every row;
    # we materialise an Inventory_category record per distinct slug so the
    # category dropdown in the admin / POS is populated immediately.
    category_lookup = _resolve_categories(all_rows)
    ctx.bump('categories_seeded', len(category_lookup))

    # ── 3. Group rows by (label, description) ─────────────────────────────────
    def _norm_size(s: str | None) -> str:
        """Canonical size key — strip whitespace, upper-case so 'xl' / 'XL' / ' XL '
        all collapse to one variant. Returned value is what we store as the
        AttributeValue (so SKU generation produces deterministic, unique codes).
        """
        return (s or '').strip().upper()

    # Normalise sizes IN-PLACE before grouping so the lot-once derivation in
    # stock_signals can group by canonical size.
    for row in all_rows:
        row['size'] = _norm_size(row.get('size'))

    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in all_rows:
        groups[(row['label'], row['description'])].append(row)

    # ── 3b. Derive opening quantities per (label, description, size) using the
    # tiered signal stack (stock_take_2026 → stock_take_2025 → lot_distributed
    # → row_count) with a sanity cap on lot inference. The audit_rows list
    # carries one entry per (label, desc, size) for stock_opening_audit.csv.
    size_qty_map, stock_audit_rows = derive_group_quantities(groups)

    # ── 3c. Pricing sanity probes (SALE vs Actual Price vs pur_price). Audit
    # only — emitted to pricing_sanity.csv.
    pricing_sanity_rows = derive_pricing_sanity(all_rows)
    ctx.pricing_sanity.extend(pricing_sanity_rows)

    # ── 3d. Column-drift validator — flags cells whose type doesn't match the
    # expected schema (catches shifted columns / data-entry typos).
    ctx.column_drift.extend(validate_product_sheet_columns(ctx.workbook_path))

    # ── 4. Iterate groups — one Inventory record per group ────────────────────
    # Counter keyed on the *truncated* prefix that ends up in product_code.
    # Two distinct descriptions can share the same prefix once truncated, so
    # we MUST key on the prefix (not the full slug) to disambiguate.
    code_counter: dict[str, int] = {}

    products_created = 0
    variants_created = 0
    shopstock_rows = 0

    for (label, description), rows in groups.items():
        # (sizes are already normalised above)
        label_slug = _slugify(label) or 'item'
        desc_slug = _slugify(description) or 'product'

        prefix = _make_prefix(label_slug, desc_slug)
        seq = code_counter.get(prefix, 0) + 1
        code_counter[prefix] = seq
        product_code = _make_product_code(prefix, seq)

        # Defence-in-depth: if a previous run left rows behind (--force), keep
        # bumping the seq until the code is actually unique in the DB. The
        # in-memory counter handles the same-run case; this handles cross-run.
        while Inventory.objects.filter(product_code=product_code).exists():
            seq += 1
            product_code = _make_product_code(prefix, seq)
        code_counter[prefix] = seq

        # A group has variants iff at least one row carries a non-empty size.
        has_variants = any(r['size'] for r in rows)

        # Separate sized and unsized rows within this group.
        sized_rows = [r for r in rows if r['size']]
        unsized_rows = [r for r in rows if not r['size']]

        # purchase_price: prefer total_unit_cost (includes indirect costs)
        purchase_price = _pick_first(rows, 'total_unit_cost', 'purchase_price')
        selling_price = _pick_first(rows, 'selling_price')
        shop_tag = _pick_first(rows, 'shop_tag') or ''

        # Category — pick the first row's tag (groups are keyed on (label,
        # description) so the category is almost always uniform within a group).
        category_slug = _pick_first(rows, 'category')
        category = category_lookup.get(category_slug) if category_slug else None

        # Inventory.quantity_in_Stock: sum of all derived qtys for no-variant
        # products; for variant products carry only the unsized-row stock on
        # the parent. Read from size_qty_map keyed on '' size for unsized.
        if not has_variants:
            # No-variant product: all rows are unsized → one entry under ''
            parent_q = size_qty_map.get((label, description, ''), 0)
        else:
            # Variant product: unsized rows (if any) carry parent stock
            parent_q = size_qty_map.get((label, description, ''), 0)

        # ── Create Inventory record ───────────────────────────────────────────
        inv = Inventory.objects.create(
            product_code=product_code,
            name=description[:100],
            label=label or None,
            bought_from=shop_tag or None,
            description=description,
            purchase_price=purchase_price,
            selling_price=selling_price,
            has_variants=has_variants,
            is_vat_exempt=False,
            quantity_in_Stock=parent_q,
            category=category,
        )
        products_created += 1

        if has_variants:
            # Record which attribute types drive this product's variant matrix.
            inv.variant_attributes.add(size_type)

        # ── ShopStock for the Inventory row (no-variant, or unsized carry) ────
        # Always create a ShopStock row for no-variant products (POS needs it
        # even when qty is 0).  For variant products, only create one if there
        # are unsized rows contributing stock.
        if not has_variants or parent_q > 0:
            ss = ShopStock.get_or_create_for(ctx.shop, inv, variant=None)
            ss.quantity = parent_q
            ss.save(update_fields=['quantity', 'last_updated'])
            shopstock_rows += 1
            ctx.qoh_get(inv.id, None)['opening_qty_imported'] += parent_q

        # ── Fuzzy corpus entry for no-variant products ────────────────────────
        if not has_variants:
            ctx.fuzzy_matcher.add(
                inv.id, None,
                description,
                f"{label} {description}",
                inv.name,
            )

        # ── Variants — one per distinct size value ────────────────────────────
        # Use the derived size_qty_map (lot-aware) rather than raw row counts.
        size_quantities: dict[str, int] = {}
        for r in sized_rows:
            sz = r['size']
            if sz in size_quantities:
                continue  # already accounted for via the map
            size_quantities[sz] = size_qty_map.get((label, description, sz), 0)

        for size_str, qty in size_quantities.items():
            # Ensure the AttributeValue exists (seed_attributes pre-seeds
            # common sizes; any non-standard value like "38.5" is created here).
            attr_val, _ = AttributeValue.objects.get_or_create(
                attribute_type=size_type,
                value=size_str,
                defaults={'display_value': size_str},
            )

            # Save with a temp SKU (ProductVariant.save() auto-generates one);
            # then set M2M and regenerate the proper "{product_code}-{size}" SKU.
            var = ProductVariant.objects.create(
                product=inv,
                quantity_in_stock=qty,
            )
            var.attribute_values.set([attr_val])

            # Regenerate SKU now that M2M relationship is populated.
            var.sku = var.generate_sku()
            var.barcode = var.sku.upper().replace(' ', '')[:32] or None
            var.save(update_fields=['sku', 'barcode'])
            variants_created += 1

            # Per-shop stock row: overwrite the seeded default with actual Q.
            ss = ShopStock.get_or_create_for(ctx.shop, inv, variant=var)
            ss.quantity = qty
            ss.save(update_fields=['quantity', 'last_updated'])
            shopstock_rows += 1

            ctx.qoh_get(inv.id, var.id)['opening_qty_imported'] += qty

            # Register multiple corpus strings so fuzzy match tolerates partial
            # descriptions from daily-sales rows.
            ctx.fuzzy_matcher.add(
                inv.id, var.id,
                description,
                f"{label} {description}",
                f"{description} {size_str}",
                inv.name,
            )

    # ── 5. Backfill product_code into stock-opening audit rows (we couldn't
    # do this in derive_group_quantities since codes are assigned per-group
    # during this loop). Build a lookup from (label, description) → code.
    code_by_group: dict[tuple[str, str], str] = {
        (inv.label or '', inv.description): inv.product_code
        for inv in Inventory.objects.filter(
            label__in=[g[0] for g in groups.keys() if g[0]],
        ) | Inventory.objects.filter(
            label__isnull=True,
            description__in=[g[1] for g in groups.keys() if not g[0]],
        )
    }
    for audit_row in stock_audit_rows:
        key = (audit_row['label'] or '', audit_row['description'])
        audit_row['product_code'] = code_by_group.get(key, '')

    ctx.stock_opening_audit.extend(stock_audit_rows)

    # ── 6. Flush phase counters into the shared tally ─────────────────────────
    ctx.bump('products_created', products_created)
    ctx.bump('variants_created', variants_created)
    ctx.bump('shopstock_rows', shopstock_rows)
    # Stock-confidence tier histogram surfaced in import_summary.txt
    for ar in stock_audit_rows:
        ctx.bump(f'stock_tier_{ar["tier"]}', 1)

    # ── 6. Post-condition: every ShopStock row for this shop must be >= 0 ─────
    neg_qs = ShopStock.objects.filter(shop=ctx.shop, quantity__lt=0)
    if neg_qs.exists():
        sample = list(
            neg_qs.values_list('inventory_item__product_code', flat=True)[:5]
        )
        raise ImportAborted(
            f"{LOG_PREFIX} Post-condition violated: {neg_qs.count()} ShopStock rows "
            f"have quantity < 0 for shop '{ctx.shop.code}'. "
            f"Sample product codes: {sample}"
        )

    ctx.log(
        f"{LOG_PREFIX} products: created {products_created} inventory + "
        f"{variants_created} variants from {len(all_rows)} rows"
    )
