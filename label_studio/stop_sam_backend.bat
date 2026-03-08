@echo off
setlocal enabledelayedexpansion
echo Stopping SAM ML backend...
set FOUND=0
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":9090 " ^| findstr LISTENING') do (
    taskkill /F /PID %%a 2>nul
    set FOUND=1
)
if !FOUND! equ 1 (
    echo SAM backend stopped.
) else (
    echo SAM backend is not running.
)
pause
