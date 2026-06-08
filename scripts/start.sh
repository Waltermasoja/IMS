#!/bin/bash
# Startup script for Railway / Render - runs migrations and starts the server
# PORT is set automatically by both platforms
cd "$(dirname "$0")/.." || exit 1

echo "Running database migrations..."
python manage.py migrate --noinput

echo "Initializing GL accounts (idempotent)..."
python manage.py init_gl_accounts || true

echo "Seeding shops, importer user, and product attributes (idempotent)..."
python manage.py create_initial_shops || true
python manage.py seed_imported_history_user || true
python manage.py seed_attributes || true

echo "Collecting static files..."
python manage.py collectstatic --noinput

# Create superuser non-interactively if credentials env vars are set.
# After first successful deploy, delete DJANGO_SUPERUSER_* vars from the
# Render dashboard so they don't linger in the environment.
if [ -n "$DJANGO_SUPERUSER_USERNAME" ] && [ -n "$DJANGO_SUPERUSER_PASSWORD" ]; then
  echo "Ensuring superuser '$DJANGO_SUPERUSER_USERNAME' exists..."
  python manage.py createsuperuser --noinput || echo "Superuser already exists or creation skipped."
fi

echo "Starting Gunicorn server..."
# --timeout 300: inventory_list and similar pages do N+1 lookups for has_variants/
# total_stock/variant_count across ~740 products; under prod latency a single
# request can take ~10 minutes. Bumping the worker timeout prevents the 30s-kill
# loop while the views are properly prefetched/annotated.
# --workers 2: one stuck worker won't block all traffic.
exec gunicorn inventorySystem.wsgi:application \
  --bind 0.0.0.0:${PORT:-8000} \
  --timeout 300 \
  --workers 2

