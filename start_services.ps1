# MeteorAI Startup Script
# Starts PostgreSQL, Streamlit, Label Studio, and the SAM ML backend
# Detects if each service is already running and skips it if so.
# Run from PowerShell: .\start_services.ps1

$PROJECT_DIR = "C:\Users\charl\meteorai"

function Test-Port($port) {
    try {
        $tcp = New-Object System.Net.Sockets.TcpClient
        $tcp.Connect("127.0.0.1", $port)
        $tcp.Close()
        return $true
    } catch {
        return $false
    }
}

Write-Host "=== MeteorAI Startup ===" -ForegroundColor Cyan

# 1. Start PostgreSQL Windows service (if not already running)
#    This is the only step that needs admin privileges.
Write-Host "`n[1/3] Checking PostgreSQL..." -ForegroundColor Yellow
$pgService = Get-Service -Name "postgresql-x64-18" -ErrorAction SilentlyContinue
if ($pgService -and $pgService.Status -eq "Running") {
    Write-Host "  PostgreSQL service is already running." -ForegroundColor Green
} elseif ($pgService) {
    Write-Host "  Starting PostgreSQL service (requesting admin)..."
    Start-Process PowerShell -Verb RunAs -ArgumentList '-Command "net start postgresql-x64-18"' -Wait
    $pgStarted = $false
    for ($i = 0; $i -lt 10; $i++) {
        Start-Sleep -Seconds 3
        $pgService = Get-Service -Name "postgresql-x64-18"
        if ($pgService.Status -eq "Running") {
            $pgStarted = $true
            break
        }
        Write-Host "  Waiting for PostgreSQL to start... ($($i + 1)/10)" -ForegroundColor Yellow
    }
    if ($pgStarted) {
        Write-Host "  PostgreSQL service started successfully." -ForegroundColor Green
    } else {
        Write-Host "  ERROR: PostgreSQL service failed to start after 30 seconds." -ForegroundColor Red
        Read-Host "`nPress Enter to exit"
        exit 1
    }
} else {
    Write-Host "  ERROR: PostgreSQL service 'postgresql-x64-18' not found." -ForegroundColor Red
    Read-Host "`nPress Enter to exit"
    exit 1
}

# 2. Start Streamlit (if not already running on port 8501)
#    Runs as current user so Python environment is correct.
Write-Host "`n[2/3] Checking Streamlit..." -ForegroundColor Yellow
if (Test-Port 8501) {
    Write-Host "  Streamlit is already running on port 8501." -ForegroundColor Green
} else {
    Write-Host "  Starting Streamlit..."
    Start-Process streamlit -ArgumentList "run", "$PROJECT_DIR\meteorite_scraper\app.py", "--server.port", "8501", "--browser.gatherUsageStats", "false" -WindowStyle Minimized
    Write-Host "  Streamlit starting at http://localhost:8501" -ForegroundColor Green
}

# 3. Start Label Studio (if not already running on port 8081)
#    Runs as current user so Python environment is correct.
Write-Host "`n[3/4] Checking Label Studio..." -ForegroundColor Yellow
if (Test-Port 8081) {
    Write-Host "  Label Studio is already running on port 8081." -ForegroundColor Green
} else {
    Write-Host "  Starting Label Studio..."
    Start-Process cmd -ArgumentList "/c `"$PROJECT_DIR\start_label_studio.bat`"" -WindowStyle Minimized
    Write-Host "  Label Studio starting at http://localhost:8081" -ForegroundColor Green
}

# 4. Start SAM ML backend (if not already running on port 9090)
#    Requires: pip install -r label_studio/requirements_sam.txt
#              python label_studio/download_sam_weights.py
Write-Host "`n[4/4] Checking SAM ML backend..." -ForegroundColor Yellow
if (Test-Port 9090) {
    Write-Host "  SAM backend is already running on port 9090." -ForegroundColor Green
} else {
    $samWeights = Get-ChildItem "$PROJECT_DIR\label_studio\sam_weights" -Filter "*.pt" -ErrorAction SilentlyContinue
    if ($samWeights) {
        Write-Host "  Starting SAM ML backend..."
        Start-Process cmd -ArgumentList "/c `"$PROJECT_DIR\label_studio\start_sam_backend.bat`"" -WindowStyle Minimized
        Write-Host "  SAM backend starting at http://localhost:9090" -ForegroundColor Green
    } else {
        Write-Host "  SAM weights not found - skipping." -ForegroundColor Gray
        Write-Host "  To enable: python label_studio/download_sam_weights.py" -ForegroundColor Gray
    }
}

# Wait for Streamlit to be ready, then open its browser tab
Write-Host "`nWaiting for Streamlit to initialize..." -ForegroundColor Yellow
Start-Sleep -Seconds 5
Start-Process "http://localhost:8501"

# Wait for Label Studio to be ready (it takes longer to start)
Write-Host "Waiting for Label Studio to initialize..." -ForegroundColor Yellow
Start-Sleep -Seconds 15
Start-Process "http://localhost:8081"

Write-Host "`n=== All services started ===" -ForegroundColor Cyan
Write-Host "  Streamlit:     http://localhost:8501"
Write-Host "  Label Studio:  http://localhost:8081"
Write-Host "  SAM backend:   http://localhost:9090"
Write-Host "  PostgreSQL:    localhost:5432"
Write-Host "`nServices are running in the background."
Write-Host "To stop all services, run: .\stop_services.ps1" -ForegroundColor Yellow
Read-Host "`nPress Enter to close this window"
