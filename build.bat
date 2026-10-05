@echo off
cd /d "%~dp0"
py -m pip install -q -r requirements.txt pyinstaller
py -m PyInstaller --noconfirm --onefile --noconsole --name BatteryTray --icon docs\icon.ico --collect-all customtkinter battery_monitor.py
echo Built dist\BatteryTray.exe
