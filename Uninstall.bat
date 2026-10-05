@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0startup.ps1" uninstall
echo Battery Tray removed from startup.
timeout /t 3 >nul
