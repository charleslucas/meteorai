# MeteorAI Startup Script
# Starts PostgreSQL, Streamlit, and Label Studio
# Detects if each service is already running and skips it if so.
# Run from PowerShell: .\start_services.ps1

$PROJECT_DIR = "C:\cygwin64\home\charl\meteorai"

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
    Start-Process streamlit -ArgumentList "run", "$PROJECT_DIR\meteorite_scraper\app.py", "--server.port", "8501" -WindowStyle Minimized
    Write-Host "  Streamlit starting at http://localhost:8501" -ForegroundColor Green
}

# 3. Start Label Studio (if not already running on port 8080)
#    Runs as current user so Python environment is correct.
Write-Host "`n[3/3] Checking Label Studio..." -ForegroundColor Yellow
if (Test-Port 8080) {
    Write-Host "  Label Studio is already running on port 8080." -ForegroundColor Green
} else {
    Write-Host "  Starting Label Studio..."
    $env:LABEL_STUDIO_LOCAL_FILES_SERVING_ENABLED = "true"
    $env:LABEL_STUDIO_LOCAL_FILES_DOCUMENT_ROOT = "$PROJECT_DIR\meteorite_scraper"
    Start-Process label-studio -ArgumentList "start", "--port", "8080" -WindowStyle Minimized
    Write-Host "  Label Studio starting at http://localhost:8080" -ForegroundColor Green
}

# Wait for Streamlit to be ready, then open its browser tab
Write-Host "`nWaiting for Streamlit to initialize..." -ForegroundColor Yellow
Start-Sleep -Seconds 5
Start-Process "http://localhost:8501"

# Wait for Label Studio to be ready (it takes longer to start)
Write-Host "Waiting for Label Studio to initialize..." -ForegroundColor Yellow
Start-Sleep -Seconds 15
Start-Process "http://localhost:8080"

Write-Host "`n=== All services started ===" -ForegroundColor Cyan
Write-Host "  Streamlit:     http://localhost:8501"
Write-Host "  Label Studio:  http://localhost:8080"
Write-Host "  PostgreSQL:    localhost:5432"
Write-Host "`nServices are running in the background."
Write-Host "To stop all services, run: .\stop_services.ps1" -ForegroundColor Yellow
Read-Host "`nPress Enter to close this window"
