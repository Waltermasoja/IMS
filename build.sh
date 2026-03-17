#!/bin/bash
# Production build script

echo "Installing Node dependencies..."
npm install

echo "Building Tailwind CSS..."
npm run build:tailwind

echo "Collecting Django static files..."
python manage.py collectstatic --noinput

echo "Build complete!"
