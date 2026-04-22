# Initialize Railway Database from Scratch
# This script sets up a completely empty Railway database

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location (Join-Path $ScriptDir '..')

Write-Host "=== Initialize Railway Database ===" -ForegroundColor Cyan
Write-Host ""

Write-Host "⚠️  WARNING: This will run ALL migrations on the Railway production database!" -ForegroundColor Yellow
Write-Host ""

# Confirm
$confirmation = Read-Host "Are you sure you want to proceed? (yes/no)"
if ($confirmation -ne "yes") {
    Write-Host "❌ Aborted" -ForegroundColor Red
    exit 0
}

Write-Host ""

# Set Railway database credentials (public URL)
Write-Host "Step 1: Setting Railway database credentials..." -ForegroundColor Yellow

# Railway PostgreSQL connection details (public URL for local access)
$env:DB_HOST = "maglev.proxy.rlwy.net"
$env:DB_PORT = "57897"
$env:DB_NAME = "railway"
$env:DB_USER = "postgres"
$env:DB_PASSWORD = "pNDvSpPwTmShhljHrqaUeULqXvCxAEmz"

# Set DATABASE_PUBLIC_URL (this is what the settings.py will use)
$env:DATABASE_PUBLIC_URL = "postgresql://postgres:pNDvSpPwTmShhljHrqaUeULqXvCxAEmz@maglev.proxy.rlwy.net:57897/railway"

# Also set individual env vars as fallback
$env:PGDATABASE = "railway"
$env:PGUSER = "postgres"
$env:PGPASSWORD = "pNDvSpPwTmShhljHrqaUeULqXvCxAEmz"
$env:PGHOST = "maglev.proxy.rlwy.net"
$env:PGPORT = "57897"
$env:POSTGRES_DB = "railway"
$env:POSTGRES_USER = "postgres"
$env:POSTGRES_PASSWORD = "pNDvSpPwTmShhljHrqaUeULqXvCxAEmz"
$env:RAILWAY_TCP_PROXY_DOMAIN = "maglev.proxy.rlwy.net"
$env:RAILWAY_TCP_PROXY_PORT = "57897"

Write-Host "✅ Database credentials set" -ForegroundColor Green
Write-Host "   Host: $env:DB_HOST" -ForegroundColor Gray
Write-Host "   Port: $env:DB_PORT" -ForegroundColor Gray
Write-Host "   Database: $env:DB_NAME" -ForegroundColor Gray
Write-Host ""

# Test database connection first
Write-Host "Step 2: Testing database connection..." -ForegroundColor Yellow
python manage.py check --database default

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "❌ Database connection failed!" -ForegroundColor Red
    Write-Host "Please check your database credentials and network connection." -ForegroundColor Yellow
    exit 1
}

Write-Host "✅ Database connection successful!" -ForegroundColor Green
Write-Host ""

# Run all migrations
Write-Host "Step 3: Running ALL Django migrations (this will take a moment)..." -ForegroundColor Yellow
Write-Host ""

python manage.py migrate --verbosity=2

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "❌ Migration failed!" -ForegroundColor Red
    Write-Host ""
    Write-Host "Checking migration status..." -ForegroundColor Yellow
    python manage.py showmigrations
    exit 1
}

Write-Host ""
Write-Host "✅ All migrations completed successfully!" -ForegroundColor Green
Write-Host ""

# Show final migration status
Write-Host "Step 4: Verifying all migrations applied..." -ForegroundColor Yellow
python manage.py showmigrations
Write-Host ""

# Initialize GL accounts (required for accounting features)
Write-Host "Step 5: Initializing GL accounts (required for accounting features)..." -ForegroundColor Yellow
python manage.py init_gl_accounts

if ($LASTEXITCODE -ne 0) {
    Write-Host "⚠️  Warning: GL accounts initialization failed or already exists" -ForegroundColor Yellow
    Write-Host "   This is okay if GL accounts were already initialized" -ForegroundColor Gray
} else {
    Write-Host "✅ GL accounts initialized!" -ForegroundColor Green
}
Write-Host ""

# Create superuser if needed
Write-Host "Step 6: Would you like to create a superuser? (optional)" -ForegroundColor Yellow
$createUser = Read-Host "Create superuser? (yes/no)"
if ($createUser -eq "yes") {
    python manage.py createsuperuser
}

Write-Host ""
Write-Host "✅ Database initialization complete!" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Test your application: https://ims-production-45b3.up.railway.app" -ForegroundColor Gray
Write-Host "  2. Access admin panel: https://ims-production-45b3.up.railway.app/admin/" -ForegroundColor Gray
Write-Host "  3. Check Railway deployment logs to ensure everything is working" -ForegroundColor Gray
Write-Host ""

