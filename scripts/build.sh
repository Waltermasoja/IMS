#!/bin/bash
# Production build script
cd "$(dirname "$0")/.." || exit 1

echo "Installing Node dependencies..."
npm install

echo "Building Tailwind CSS..."
npm run build:tailwind

echo "Collecting Django static files..."
python manage.py collectstatic --noinput

echo "Build complete!"
