# MeteorAI Shutdown Script
# Stops PostgreSQL, Streamlit, Label Studio, and the SAM ML backend
# Run from PowerShell: .\stop_services.ps1

Write-Host "=== MeteorAI Shutdown ===" -ForegroundColor Cyan

# 1. Stop SAM ML backend (process listening on port 9090)
Write-Host "`n[1/4] Stopping SAM ML backend..." -ForegroundColor Yellow
$samStopped = $false
try {
    $samPids = (netstat -ano | Select-String ":9090 .*LISTENING") |
        ForEach-Object { ($_ -split "\s+")[-1] } | Select-Object -Unique
    foreach ($procId in $samPids) {
        if ($procId -match "^\d+$") {
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
            $samStopped = $true
        }
    }
} catch {}
if ($samStopped) {
    Write-Host "  SAM backend stopped." -ForegroundColor Green
} else {
    Write-Host "  SAM backend is not running." -ForegroundColor Gray
}

# 2. Stop Label Studio
Write-Host "`n[2/4] Stopping Label Studio..." -ForegroundColor Yellow
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

# 3. Stop Streamlit
Write-Host "`n[3/4] Stopping Streamlit..." -ForegroundColor Yellow
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

# 4. Stop PostgreSQL Windows service
Write-Host "`n[4/4] Stopping PostgreSQL..." -ForegroundColor Yellow
$pgService = Get-Service -Name "postgresql-x64-18" -ErrorAction SilentlyContinue
if ($pgService -and $pgService.Status -eq "Running") {
    Start-Process PowerShell -Verb RunAs -ArgumentList '-Command "net stop postgresql-x64-18"' -Wait
    Write-Host "  PostgreSQL service stopped." -ForegroundColor Green
} else {
    Write-Host "  PostgreSQL service is not running." -ForegroundColor Gray
}

Write-Host "`n=== All services stopped ===" -ForegroundColor Cyan
Read-Host "`nPress Enter to close this window"
