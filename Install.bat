@echo off
cd /d "%~dp0"
echo Installing Python packages...
py -m pip install -q -r requirements.txt || (echo Python not found. Install it from https://www.python.org/downloads/ & pause & exit /b 1)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0startup.ps1" install
start "" pyw battery_monitor.py
echo Done. Battery Tray now starts with Windows.
timeout /t 3 >nul
