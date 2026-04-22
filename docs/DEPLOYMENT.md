# Deployment Guide

This guide explains how to deploy the Inventory Management System to production.

## Prerequisites

- Node.js (for building Tailwind CSS)
- Python 3.11+
- PostgreSQL or MySQL (recommended for production)

## Production Build Steps

### Automatic Build (Recommended)

The project is configured to automatically build Tailwind CSS when you run `npm install`. This happens via the `postinstall` script in package.json.

**Simply run:**
```bash
npm install
```

The CSS will be automatically built and minified.

### Manual Build

If you need to build manually:

```bash
# Install dependencies
npm install

# Build minified CSS for production
npm run build:tailwind:prod

# Collect Django static files
python manage.py collectstatic --noinput
```

## Platform-Specific Instructions

### Heroku

Add to your `Procfile`:
```
release: python manage.py migrate && npm run build:tailwind:prod && python manage.py collectstatic --noinput
web: gunicorn inventorySystem.wsgi
```

### Railway / Render

This repository’s production entrypoint is `scripts/start.sh` (migrations, `init_gl_accounts`, `collectstatic`, then Gunicorn). The root `Procfile` uses:

```bash
web: bash scripts/start.sh
```

**Render (`render.yaml`):** build is `pip install -r requirements.txt`; start is `bash scripts/start.sh`.

**Manual equivalent (if not using the script):**

**Build Command:**
```bash
npm install && python manage.py migrate && python manage.py collectstatic --noinput
```

**Start Command:**
```bash
gunicorn inventorySystem.wsgi:application --bind 0.0.0.0:${PORT:-8000}
```

For a full Node + Tailwind + `collectstatic` build in one step, use `bash scripts/build.sh` from the repository root (after activating your Python environment).

### Docker

Add to your `Dockerfile`:
```dockerfile
# Install Node.js
RUN apt-get update && apt-get install -y nodejs npm

# Copy package files
COPY package*.json ./
RUN npm install

# Copy rest of application
COPY . .

# Collect static files
RUN python manage.py collectstatic --noinput
```

### Traditional Server (VPS)

```bash
# Clone repository
git clone <your-repo-url>
cd IMS

# Install Python dependencies
pip install -r requirements.txt

# Install Node.js dependencies and build CSS
npm install

# Run migrations
python manage.py migrate

# Initialize GL accounts (IMPORTANT - first time only!)
python manage.py init_gl_accounts

# Collect static files
python manage.py collectstatic --noinput

# Start server with gunicorn
gunicorn inventorySystem.wsgi --bind 0.0.0.0:8000
```

## Important: Static Files in Production

The app uses WhiteNoise to serve static files in production. Make sure:

1. `DEBUG = False` in production settings
2. `ALLOWED_HOSTS` is properly configured
3. Run `collectstatic` after building CSS

## Environment Variables

Set these in production:

```bash
DEBUG=False
SECRET_KEY=<your-secret-key>
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com
DATABASE_URL=<your-database-url>  # if using PostgreSQL/MySQL
```

## Troubleshooting

**CSS not loading:**
- Verify `output.css` exists in `static/css/`
- Check that `collectstatic` ran successfully
- Ensure WhiteNoise is in MIDDLEWARE settings

**"output.css not found" error:**
- Run `npm install` (triggers automatic build via postinstall)
- Or manually run `npm run build:tailwind:prod`

## Development vs Production

**Development (local):**
```bash
npm run watch:tailwind  # Auto-rebuild CSS on changes
python manage.py runserver
```

**Production:**
```bash
npm run build:tailwind:prod  # One-time minified build
gunicorn inventorySystem.wsgi
```
