#!/bin/bash
# Railway startup script - runs migrations and starts the server

echo "Running database migrations..."
python manage.py migrate --noinput

echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Starting Gunicorn server..."
exec gunicorn inventorySystem.wsgi:application --bind 0.0.0.0:$PORT

