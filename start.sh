#!/bin/bash
# Startup script for Railway / Render - runs migrations and starts the server
# PORT is set automatically by both platforms

echo "Running database migrations..."
python manage.py migrate --noinput

echo "Initializing GL accounts (idempotent)..."
python manage.py init_gl_accounts || true

echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Starting Gunicorn server..."
exec gunicorn inventorySystem.wsgi:application --bind 0.0.0.0:${PORT:-8000}

