# CDN to Local Assets Migration

This document tracks the migration from CDN dependencies to local assets to prevent browser tracking protection issues.

## Completed Migrations

### 1. Tailwind CSS
- **From**: CDN (Play CDN)
- **To**: Local build via npm
- **Files**:
  - `static/css/input.css` (source)
  - `static/css/output.css` (generated, 69KB)
- **Config**: `tailwind.config.js`
- **Build**: `npm run build:tailwind` or `npm run watch:tailwind`

### 2. Alpine.js
- **From**: `https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js`
- **To**: `static/js/alpine.min.js` (44KB)
- **Used in**: `templates/base.html:13`

### 3. Font Awesome
- **From**: `https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css`
- **To**:
  - CSS: `static/css/fontawesome/all.min.css` (88KB)
  - Fonts: `static/css/fontawesome/webfonts/` (3 files, 251KB total)
    - `fa-solid-900.woff2` (124KB)
    - `fa-brands-400.woff2` (103KB)
    - `fa-regular-400.woff2` (24KB)
- **Used in**: `templates/base.html:16`
- **Note**: CSS paths were updated to reference correct font locations

### 4. ApexCharts
- **From**: `https://cdn.jsdelivr.net/npm/apexcharts`
- **To**: `static/js/apexcharts.min.js` (568KB)
- **Used in**:
  - `templates/inventory/dashboard.html:136`
  - `templates/inventory/dashboard_modern.html:213`

## Still Using CDN (Optional to migrate)

### Google Fonts
- **Current**: `https://fonts.googleapis.com/css2?family=Inter`
- **Used in**: `templates/base.html:19`
- **Note**: Low priority, fonts rarely blocked by tracking prevention

## Benefits

✅ **No more tracking prevention issues** - All assets served from your domain
✅ **Better offline support** - Works without internet access (once loaded)
✅ **Improved performance** - No external DNS lookups or redirects
✅ **More control** - Specific versions, no unexpected updates
✅ **Privacy friendly** - No data shared with third-party CDNs

## Production Deployment

All local assets should be committed to git (they're included in the repository).

**Build process:**
```bash
npm install          # Installs Tailwind and builds CSS automatically
python manage.py collectstatic --noinput
```

The `postinstall` script in `package.json` automatically builds Tailwind CSS after `npm install`.

## Total Size

| Asset | Size |
|-------|------|
| Tailwind CSS | 69KB |
| Alpine.js | 44KB |
| Font Awesome CSS | 88KB |
| Font Awesome Fonts | 251KB |
| ApexCharts | 568KB |
| **Total** | **~1020KB (1MB)** |

This is acceptable for modern web applications and ensures reliable functionality.

## Maintenance

- **Tailwind**: Rebuild after template changes: `npm run build:tailwind`
- **Alpine.js**: Update by re-downloading from jsdelivr.net
- **Font Awesome**: Update by re-downloading from cdnjs.cloudflare.com
- **ApexCharts**: Update by re-downloading from jsdelivr.net

## Related Files

- `.gitignore` - Excludes node_modules but includes built assets
- `package.json` - Contains Tailwind build scripts
- `tailwind.config.js` - Tailwind configuration
- `DEPLOYMENT.md` - Production deployment instructions
