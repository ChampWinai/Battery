"""หูฟังผ่าน HeadsetControl (headsetcontrol.exe)"""
import json
import shutil
import subprocess
from batterytray.config import APP_DIR, NO_WINDOW


# ---------- 3. HeadsetControl ----------

HEADSETCONTROL_URL = "https://github.com/Sapd/HeadsetControl/releases"


def headsetcontrol_exe():
    local = APP_DIR / "headsetcontrol.exe"
    return str(local) if local.exists() else shutil.which("headsetcontrol")


def headsetcontrol_parse(text):
    """{key: (ชื่อ, (pct, charging) หรือ None)} จาก JSON ของ headsetcontrol -o json"""
    try:
        data = json.loads(text)
    except ValueError:
        return {}
    res = {}
    for d in data.get("devices", []):
        key = f"hc:{d.get('id_vendor', '')}:{d.get('id_product', '')}"
        name = d.get("device") or d.get("product") or "Headset"
        bat = d.get("battery") or {}
        level, status = bat.get("level"), bat.get("status", "")
        ok = isinstance(level, int) and 0 <= level <= 100 and status in ("BATTERY_AVAILABLE", "BATTERY_CHARGING")
        res[key] = (name, (level, status == "BATTERY_CHARGING") if ok else None)
    return res


def headsetcontrol_query():
    exe = headsetcontrol_exe()
    if not exe:
        return {}
    try:
        out = subprocess.run([exe, "-o", "json"], capture_output=True, text=True,
                             encoding="utf-8", timeout=15, creationflags=NO_WINDOW).stdout
    except (OSError, subprocess.TimeoutExpired):
        return {}
    return headsetcontrol_parse(out)


def headset_devices():
    return [{"key": key, "kind": "headset", "name": name,
             "read": lambda k=key: (headsetcontrol_query().get(k) or (None, None))[1]}
            for key, (name, _) in headsetcontrol_query().items()]
