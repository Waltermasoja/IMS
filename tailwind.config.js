/** @type {import('tailwindcss').Config} */
const colors = require('tailwindcss/colors');

module.exports = {
  content: [
    './templates/**/*.html',
    './inventory/templates/**/*.html',
    './accounting/templates/**/*.html',
  ],
  theme: {
    extend: {
      // ─── Semantic colour tokens ──────────────────────────────────────────
      // Map each role to a palette object so classes like bg-primary-50,
      // text-primary-600, border-primary-200 all resolve.
      colors: {
        primary: colors.blue,     // actions, links, primary buttons
        success: colors.green,    // sales, positive balances, completed
        danger:  colors.red,      // destructive, errors, shortages
        warning: colors.amber,    // caution, variance, low stock
        info:    colors.indigo,   // reports, VAT, informational
        finance: colors.purple,   // accounting, ledger, journal
        brand:   colors.emerald,  // POS header chip, "IMS Pro" mark
      },

      // ─── Canonical radii ──────────────────────────────────────────────────
      // rounded-card = large containers (pages, panels)
      // rounded-btn  = interactive elements (buttons, inputs, small cards)
      // rounded-pill = badges, avatars
      borderRadius: {
        card: '1rem',
        btn:  '0.75rem',
        pill: '9999px',
      },

      // ─── Canonical shadows ───────────────────────────────────────────────
      // shadow-card     = resting cards (ambient separation)
      // shadow-elevated = hover / popover / dropdown
      // shadow-overlay  = modals, floating surfaces
      boxShadow: {
        card:     '0 1px 2px 0 rgb(0 0 0 / 0.05)',
        elevated: '0 4px 6px -1px rgb(0 0 0 / 0.08), 0 2px 4px -2px rgb(0 0 0 / 0.06)',
        overlay:  '0 20px 25px -5px rgb(0 0 0 / 0.1), 0 8px 10px -6px rgb(0 0 0 / 0.08)',
      },

      // ─── Typography scale ────────────────────────────────────────────────
      // Keep Tailwind defaults; expose semantic sizes for headings so
      // page titles stay consistent across templates.
      fontSize: {
        'page-title':    ['1.5rem',  { lineHeight: '2rem',    fontWeight: '700' }],  // 24px
        'section-title': ['1rem',    { lineHeight: '1.5rem',  fontWeight: '600' }],  // 16px
        'stat-value':    ['1.5rem',  { lineHeight: '2rem',    fontWeight: '700' }],  // 24px
      },
    },
  },
  plugins: [],
};
