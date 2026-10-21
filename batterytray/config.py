"""ค่าคงที่, ไฟล์ cache และ error log"""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import time


FROZEN = getattr(sys, "frozen", False)
# โฟลเดอร์ของ exe หรือโฟลเดอร์ repo (ที่มี battery_monitor.py) ตอนรันจากซอร์ส
APP_DIR = Path(sys.executable).parent if FROZEN else Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("APPDATA", APP_DIR)) / "BatteryTray"
CACHE = DATA_DIR / "battery_cache.json"
NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

VERSION = "1.9.0"
RELEASES_PAGE = "https://github.com/ChampWinai/Battery/releases/latest"
RELEASES_API = "https://api.github.com/repos/ChampWinai/Battery/releases/latest"
UPDATE_EVERY_S = 6 * 3600  # + เช็คทุกครั้งที่เปิดแอป


EXE_NAME = "BatteryTray.exe"



DEFAULTS = {"interval": 60, "alert": 20, "hidden": [], "names": {}, "notify_full": True}


def load_cache():
    old = APP_DIR / "battery_cache.json"
    if not CACHE.exists() and old.exists():
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        shutil.move(old, CACHE)
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


ERROR_LOG = DATA_DIR / "error.log"


def log_error(where):
    """ต่อท้าย traceback ลง %APPDATA%\\BatteryTray\\error.log (ตัดเหลือ ~200 KB)"""
    import traceback
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if ERROR_LOG.exists() and ERROR_LOG.stat().st_size > 200_000:
            ERROR_LOG.write_text(ERROR_LOG.read_text(encoding="utf-8")[-100_000:], encoding="utf-8")
        with ERROR_LOG.open("a", encoding="utf-8") as f:
            f.write(f"--- {time.strftime('%Y-%m-%d %H:%M:%S')} v{VERSION} {where}\n{traceback.format_exc()}\n")
    except OSError:
        pass


def save_cache(cache):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
