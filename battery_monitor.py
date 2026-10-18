#!/usr/bin/env python3
"""Battery Tray — แสดง % แบตเมาส์/คีย์บอร์ด/หูฟังไร้สาย ข้างนาฬิกา Windows

แหล่งข้อมูล (batterytray/devices/)
1. compx         ดองเกิล 2.4G Compx/ATK (VID 3554) — VXE, ATK, Aula
2. logitech      Logitech HID++ 2.0 (Unifying / Bolt / Lightspeed / สาย)
3. headsetcontrol หูฟัง SteelSeries, Corsair, HyperX ฯลฯ ผ่าน headsetcontrol.exe
4. bluetooth     อุปกรณ์ Bluetooth ที่ Windows รู้ค่าแบต
5. nobattery     อุปกรณ์ที่ไม่ส่งค่าแบต (แสดงแค่สถานะการเชื่อมต่อ)

รัน:  pyw battery_monitor.py        ทดสอบ:  py battery_monitor.py --test
"""
import subprocess
import sys

try:
    import customtkinter  # noqa: F401
    import hid  # noqa: F401
    import pystray  # noqa: F401
    from PIL import Image  # noqa: F401
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "hidapi", "pystray", "pillow", "customtkinter"])

if __name__ == "__main__":
    if "--test" in sys.argv:
        from batterytray.selftest import test
        test()
    else:
        from batterytray.app import app
        app()
