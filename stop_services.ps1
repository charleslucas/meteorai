# MeteorAI Shutdown Script
# Stops PostgreSQL, Streamlit, and Label Studio
# Run from PowerShell: .\stop_services.ps1

Write-Host "=== MeteorAI Shutdown ===" -ForegroundColor Cyan

# 1. Stop Label Studio
Write-Host "`n[1/3] Stopping Label Studio..." -ForegroundColor Yellow
$lsProcs = Get-Process -Name "label-studio" -ErrorAction SilentlyContinue
if ($lsProcs) {
    $lsProcs | Stop-Process -Force
    Write-Host "  Label Studio stopped." -ForegroundColor Green
} else {
    # Label Studio may run as a Python process
    $pyProcs = Get-Process -Name "python*" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match "label.studio" -or $_.CommandLine -match "label_studio" }
    if ($pyProcs) {
        $pyProcs | Stop-Process -Force
        Write-Host "  Label Studio stopped." -ForegroundColor Green
    } else {
        Write-Host "  Label Studio is not running." -ForegroundColor Gray
    }
}

# 2. Stop Streamlit
Write-Host "`n[2/3] Stopping Streamlit..." -ForegroundColor Yellow
$stProcs = Get-Process -Name "streamlit" -ErrorAction SilentlyContinue
if ($stProcs) {
    $stProcs | Stop-Process -Force
    Write-Host "  Streamlit stopped." -ForegroundColor Green
} else {
    $pyProcs = Get-Process -Name "python*" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match "streamlit" }
    if ($pyProcs) {
        $pyProcs | Stop-Process -Force
        Write-Host "  Streamlit stopped." -ForegroundColor Green
    } else {
        Write-Host "  Streamlit is not running." -ForegroundColor Gray
    }
}

# 3. Stop PostgreSQL Windows service
Write-Host "`n[3/3] Stopping PostgreSQL..." -ForegroundColor Yellow
$pgService = Get-Service -Name "postgresql-x64-18" -ErrorAction SilentlyContinue
if ($pgService -and $pgService.Status -eq "Running") {
    Start-Process PowerShell -Verb RunAs -ArgumentList '-Command "net stop postgresql-x64-18"' -Wait
    Write-Host "  PostgreSQL service stopped." -ForegroundColor Green
} else {
    Write-Host "  PostgreSQL service is not running." -ForegroundColor Gray
}

Write-Host "`n=== All services stopped ===" -ForegroundColor Cyan
Read-Host "`nPress Enter to close this window"
