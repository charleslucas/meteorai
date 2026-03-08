@echo off
echo Stopping Label Studio...
taskkill /F /IM label-studio.exe /T 2>nul
if %errorlevel% equ 0 (
    echo Label Studio stopped.
) else (
    echo Label Studio was not running.
)
pause
