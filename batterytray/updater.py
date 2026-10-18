"""อัปเดตตัวเองจาก GitHub Releases"""
from pathlib import Path
import json
import os
import shutil
import sys
import time
from batterytray.config import EXE_NAME, FROZEN, RELEASES_API


def latest_release(api=RELEASES_API):
    """{tag, url, asset_url, asset_size} ของ Release ล่าสุด หรือ None ถ้าเช็คไม่ได้ (ออฟไลน์ ฯลฯ)"""
    import urllib.request
    try:
        req = urllib.request.Request(api, headers={"User-Agent": "BatteryTray"})
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.load(r)
        asset = next((a for a in d.get("assets", []) if a.get("name") == EXE_NAME), {})
        return {"tag": d["tag_name"], "url": d["html_url"],
                "asset_url": asset.get("browser_download_url"), "asset_size": asset.get("size")}
    except Exception:
        return None


def download_update(url, size, dest):
    """โหลด exe ใหม่ลง dest — ตรวจขนาดตรงกับ Release และเป็นไฟล์ exe (ขึ้นต้น MZ)"""
    import urllib.request
    part = dest.with_name(dest.name + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "BatteryTray"})
    with urllib.request.urlopen(req, timeout=60) as r, part.open("wb") as f:
        shutil.copyfileobj(r, f)
    data_ok = part.stat().st_size == size and part.read_bytes()[:2] == b"MZ"
    if not data_ok:
        part.unlink(missing_ok=True)
        raise ValueError(f"ไฟล์อัปเดตไม่สมบูรณ์ ({part.name})")
    os.replace(part, dest)


def swap_exe(target, new):
    """แทน target ด้วย new — exe ที่กำลังรันเปลี่ยนชื่อได้แต่เขียนทับไม่ได้ จึงย้ายตัวเดิมไปเป็น .old ก่อน"""
    old = target.with_name(target.name + ".old")
    old.unlink(missing_ok=True)
    os.replace(target, old)
    try:
        os.replace(new, target)
    except OSError:
        os.replace(old, target)  # คืนตัวเดิม
        raise


def cleanup_old_exe():
    """ลบ BatteryTray.exe.old ที่เหลือจากการอัปเดต (ตัวเก่าอาจยังปิดไม่เสร็จ จึงลองซ้ำ)"""
    if not FROZEN:
        return
    old = Path(sys.executable).with_name(Path(sys.executable).name + ".old")
    for _ in range(30):
        try:
            old.unlink(missing_ok=True)
            return
        except OSError:
            time.sleep(1)


def is_newer(tag, current):
    def parse(v):
        return tuple(int(x) for x in v.lstrip("vV").split(".") if x.isdigit())
    try:
        return parse(tag) > parse(current)
    except ValueError:
        return False
