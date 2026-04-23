# IMS UI partials

Headless Django template partials. All visuals are driven by Tailwind utility
classes; no component CSS layer. Partials use the canonical design tokens
defined in `tailwind.config.js` — colour aliases (primary/success/danger/…),
radii (`rounded-card`, `rounded-btn`, `rounded-pill`), and shadows
(`shadow-card`, `shadow-elevated`, `shadow-overlay`).

## Two patterns

### 1. Simple stamps — single `{% include with … %}`
Use when the partial doesn't need body content.

- `ui/stat_card.html`
- `ui/button.html`
- `ui/badge.html`
- `ui/empty_state.html`
- `ui/breadcrumb.html`
- `ui/form_field.html` (wraps a pre-rendered Django form field)

Example:
```django
{% include 'ui/stat_card.html' with label="Low Stock" value=low_count icon="fa-box" color="warning" %}
```

### 2. Wrappers — `_start.html` + `_end.html` pair
Use when body content needs template tags or is complex HTML.

- `ui/card_start.html` / `ui/card_end.html`
- `ui/page_header_start.html` / `ui/page_header_end.html`
- `ui/modal_start.html` / `ui/modal_end.html`

Example:
```django
{% include 'ui/card_start.html' with title="Recent Sales" icon="fa-receipt" %}
  <table class="w-full text-sm">…</table>
{% include 'ui/card_end.html' %}
```

## Colour token convention

`color` arg accepts: `primary`, `success`, `danger`, `warning`, `info`,
`finance`, `brand`, `gray` (neutral fallback).

## Responsive tables

`ui/table.html` is the exception — it takes structured data (headers + rows)
and renders a `<table>` on `md:+` and a card stack below.
