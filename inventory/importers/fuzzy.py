"""
rapidfuzz-based product matcher for daily-sales descriptions.

Each daily-sales row carries a free-text description like
`"china daisy brown/be"` or `"wioma black/grey w stripe"` that needs to map
onto a master product (Inventory + optional ProductVariant) so we can decrement
stock and post COGS correctly.

We match against a pre-built corpus of `(label + name + description)` strings
keyed to (Inventory.id, ProductVariant.id_or_None). Every decision (matched
*and* skipped) is logged so the operator can audit borderline scores.

Threshold default 85 (token_set_ratio). At 85 we accept obvious matches like
`"wioma black grey scotch dress"` ↔ `"wioma | black/grey scotch dress | 44"`,
but reject dangerous near-misses. Borderline scores 80-84 surface in the
unmatched CSV with the *suggested* match included for human review.
"""
from collections import namedtuple
from rapidfuzz import fuzz, process

MatchResult = namedtuple('MatchResult', ['inventory_id', 'variant_id', 'score', 'matched_text'])


class FuzzyMatcher:
    """Holds a corpus and runs name → product matches.

    Build once per importer run (corpus from products phase), call `match()`
    for each daily-sales row.
    """

    def __init__(self, threshold: int = 85):
        self.threshold = threshold
        # corpus_text → (inventory_id, variant_id_or_None)
        self._corpus: dict[str, tuple[int, int | None]] = {}
        self.decisions: list[dict] = []   # for fuzzy_match_decisions.csv

    def add(self, inventory_id: int, variant_id: int | None, *parts: str) -> None:
        """Register one (product, variant) under one or more searchable strings.

        We register multiple strings per variant so a description matches even
        if the operator wrote `"wioma blue dress"` while the master record is
        `"wioma | blue chiffon dress mermaid cut | 44"`. The longest meaningful
        substring usually wins.
        """
        for part in parts:
            text = (part or '').strip().lower()
            if not text:
                continue
            # First registration wins for collisions — alphabetical earliest variant.
            self._corpus.setdefault(text, (inventory_id, variant_id))

    def match(self, raw_description: str, sheet: str, row_index: int) -> MatchResult | None:
        """Return the best match above threshold, or None. Always logs a decision."""
        query = (raw_description or '').strip().lower()
        if not query or not self._corpus:
            self.decisions.append({
                'sheet': sheet, 'row': row_index, 'raw_description': raw_description,
                'matched_product_id': '', 'matched_variant_id': '',
                'matched_text': '', 'score': 0, 'decision': 'no_query_or_corpus',
            })
            return None

        best = process.extractOne(
            query, self._corpus.keys(),
            scorer=fuzz.token_set_ratio,
            score_cutoff=0,   # we apply our own threshold below for logging
        )
        if best is None:
            self.decisions.append({
                'sheet': sheet, 'row': row_index, 'raw_description': raw_description,
                'matched_product_id': '', 'matched_variant_id': '',
                'matched_text': '', 'score': 0, 'decision': 'no_match',
            })
            return None

        matched_text, score, _ = best
        inv_id, var_id = self._corpus[matched_text]

        decision = 'accepted' if score >= self.threshold else 'below_threshold'
        self.decisions.append({
            'sheet': sheet, 'row': row_index, 'raw_description': raw_description,
            'matched_product_id': inv_id, 'matched_variant_id': var_id or '',
            'matched_text': matched_text, 'score': round(score, 1), 'decision': decision,
        })

        if score < self.threshold:
            return None
        return MatchResult(inv_id, var_id, score, matched_text)

    def __len__(self):
        return len(self._corpus)
