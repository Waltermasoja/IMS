# IMS Template Modernization Script
# This script replaces old Bootstrap templates with modern Tailwind versions

Write-Host "🚀 IMS Template Modernization Script" -ForegroundColor Cyan
Write-Host "=====================================" -ForegroundColor Cyan
Write-Host ""

# Check if we're in the right directory
if (-not (Test-Path "templates/inventory")) {
    Write-Host "❌ Error: Please run this script from the IMS root directory" -ForegroundColor Red
    exit 1
}

# Create backup directory
$backupDir = "templates/inventory/backup_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
Write-Host "📁 Created backup directory: $backupDir" -ForegroundColor Green

# Files to update
$templates = @(
    "sales_summary"
)

$updated = 0
$skipped = 0

foreach ($template in $templates) {
    $modernFile = "templates/inventory/${template}_modern.html"
    $targetFile = "templates/inventory/${template}.html"
    $backupFile = "$backupDir/${template}.html"
    
    if (Test-Path $modernFile) {
        # Backup original
        if (Test-Path $targetFile) {
            Copy-Item $targetFile $backupFile -Force
            Write-Host "💾 Backed up: $template.html" -ForegroundColor Yellow
        }
        
        # Copy modern version
        Copy-Item $modernFile $targetFile -Force
        Write-Host "✅ Updated: $template.html" -ForegroundColor Green
        $updated++
    } else {
        Write-Host "⏭️  Skipped: $template.html (modern version not found)" -ForegroundColor Gray
        $skipped++
    }
}

Write-Host ""
Write-Host "=====================================" -ForegroundColor Cyan
Write-Host "✨ Modernization Complete!" -ForegroundColor Green
Write-Host "   Updated: $updated files" -ForegroundColor Green
Write-Host "   Skipped: $skipped files" -ForegroundColor Yellow
Write-Host "   Backups: $backupDir" -ForegroundColor Cyan
Write-Host ""
Write-Host "🔄 Please restart your Django server to see the changes" -ForegroundColor Cyan
