#!/usr/bin/env python3
"""Battery Tray — แสดง % แบตเมาส์/คีย์บอร์ด/หูฟังไร้สาย ข้างนาฬิกา Windows

แหล่งข้อมูล
1. ดองเกิล 2.4G Compx/ATK (VID 3554 — VXE, ATK, Aula และแบรนด์ที่ใช้ดองเกิลเดียวกัน)
   - เมาส์ (ถอดจาก ATK HUB): ส่ง [08 04 00.. cs] 17 ไบต์, cs = 0x55 - ผลรวมไบต์ก่อนหน้า
     ตอบ r[2]=status(0=ok) r[6]=% r[7]=ชาร์จ
   - คีย์บอร์ด AULA (womier-l65-linux): ส่ง [13 4a 01 00 .. cs] 20 ไบต์, cs = ผลรวม 19 ไบต์แรก
     ตอบ r[1]&0x7f=0x4a r[5]=%
2. Logitech HID++ 2.0 (Unifying / Bolt / Lightspeed / สาย) — feature 0x1004, 0x1000, 0x1001
3. HeadsetControl (headsetcontrol.exe) — หูฟัง Logitech, SteelSeries, Corsair, HyperX ฯลฯ
4. อุปกรณ์ Bluetooth ที่ Windows รู้ค่าแบต (DEVPKEY_Bluetooth_Battery)

รัน:  pyw battery_monitor.py        ทดสอบ:  py battery_monitor.py --test
"""
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

try:
    import hid
    import pystray
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "hidapi", "pystray", "pillow", "customtkinter"])
    import hid
    import pystray
    from PIL import Image, ImageDraw, ImageFont

FROZEN = getattr(sys, "frozen", False)
APP_DIR = Path(sys.executable).parent if FROZEN else Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("APPDATA", APP_DIR)) / "BatteryTray"
CACHE = DATA_DIR / "battery_cache.json"
NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

VERSION = "1.5.1"
RELEASES_PAGE = "https://github.com/ChampWinai/Battery/releases/latest"
RELEASES_API = "https://api.github.com/repos/ChampWinai/Battery/releases/latest"
UPDATE_EVERY_S = 24 * 3600


EXE_NAME = "BatteryTray.exe"


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


# ---------- 1. ดองเกิล Compx ----------

COMPX_VIDS = {0x3554}


def mouse_frame():
    f = [0x08, 0x04] + [0] * 15
    f[-1] = (0x55 - sum(f[:-1])) & 0xFF
    return bytes(f)


def mouse_parse(r):
    if len(r) < 10 or r[0] != 0x08 or r[1] != 0x04 or r[2] != 0:
        return None
    return r[6], bool(r[7])


def kb_frame():
    f = bytearray(20)
    f[0], f[1], f[2] = 0x13, 0x4A, 1
    f[19] = sum(f[:19]) & 0xFF
    return bytes(f)


def kb_parse(r):
    if len(r) < 7 or r[0] != 0x13 or (r[1] & 0x7F) != 0x4A or not 0 < r[5] <= 100:
        return None
    return r[5], None


PROTOCOLS = {"mouse": (mouse_frame(), mouse_parse), "keyboard": (kb_frame(), kb_parse)}


def compx_query(path, kind, tries=8):
    """คืน (pct, charging) หรือ None ถ้าไม่ตอบ (หลับ/ไม่ใช่โปรโตคอลนี้)"""
    frame, parse = PROTOCOLS[kind]
    dev = hid.device()
    try:
        dev.open_path(path)
    except OSError:
        return None
    try:
        for _ in range(tries):
            if dev.write(frame) < 0:
                return None
            for _ in range(5):
                r = dev.read(64, 200)
                if not r:
                    break
                got = parse(r)
                if got:
                    return got
            time.sleep(0.2)
    except OSError:
        pass
    finally:
        dev.close()
    return None


def compx_devices(kinds):
    labels = {"mouse": "เมาส์", "keyboard": "คีย์บอร์ด", None: "อุปกรณ์"}
    paths = {f"{d['vendor_id']:04x}:{d['product_id']:04x}": d["path"]
             for d in hid.enumerate() if d["vendor_id"] in COMPX_VIDS and d["usage_page"] == 0xFF02}
    devices = []
    for key, path in paths.items():
        dev = {"key": key, "kind": kinds.get(key), "name": f"{labels[kinds.get(key)]} 2.4G ({key})"}

        def read(path=path, key=key, dev=dev):
            kind = kinds.get(key)
            for k in [kind] if kind else PROTOCOLS:
                res = compx_query(path, k, tries=8 if kind else 3)
                if res:
                    kinds[key] = dev["kind"] = k
                    dev["name"] = f"{labels[k]} 2.4G ({key})"
                    return res
            return None

        dev["read"] = read
        devices.append(dev)
    return devices


# ---------- 2. Logitech HID++ 2.0 ----------

LOGI_VID, SWID = 0x046D, 0x0A
LOGI_KINDS = {0: "keyboard", 3: "mouse", 4: "mouse", 5: "mouse", 8: "headset"}
# ponytail: เส้นโค้งแรงดัน Li-ion แบบหยาบ (mV, %) สำหรับรุ่นที่บอกแค่โวลต์ (0x1001) — ปรับได้ถ้าคลาดเคลื่อน
VOLT_CURVE = [(4150, 100), (4000, 85), (3900, 70), (3800, 50), (3700, 30), (3600, 15), (3500, 5), (3400, 0)]


def hidpp_request(dev, idx, feat, fn, params=b"", timeout=0.5):
    """ส่งคำขอ HID++ long (0x11) แล้วคืน payload 16 ไบต์ของคำตอบ หรือ None"""
    pkt = bytes([0x11, idx, feat, (fn << 4) | SWID]) + params
    dev.write(pkt.ljust(20, b"\0"))
    end = time.time() + timeout
    while time.time() < end:
        r = dev.read(64, 100)
        if not r or r[1] != idx:
            continue
        if r[2] == 0xFF and r[3] == feat:  # error ของ HID++ 2.0
            return None
        if r[0] in (0x10, 0x11) and r[2] == 0x8F:  # error ของ HID++ 1.0 (ไม่มีอุปกรณ์ที่ index นี้)
            return None
        if r[0] == 0x11 and r[2] == feat and r[3] == pkt[3]:
            return bytes(r[4:20])
    return None


def hidpp_feature(dev, idx, feature_id, timeout=0.5):
    r = hidpp_request(dev, idx, 0x00, 0, feature_id.to_bytes(2, "big"), timeout)
    return r[0] if r and r[0] else None


def volt_to_pct(mv):
    for (v1, p1), (v2, p2) in zip(VOLT_CURVE, VOLT_CURVE[1:]):
        if mv >= v2:
            return max(0, min(100, round(p2 + (p1 - p2) * (mv - v2) / (v1 - v2))))
    return 0


def logi_battery(dev, idx):
    """อ่านแบตด้วย feature ที่อุปกรณ์มี: 0x1004 → 0x1000 → 0x1001"""
    fi = hidpp_feature(dev, idx, 0x1004)
    if fi:
        r = hidpp_request(dev, idx, fi, 1)
        if r:
            pct = r[0] or {8: 100, 4: 60, 2: 20, 1: 5}.get(r[1] & 0x0F, 0)
            return pct, r[2] in (1, 2, 3)
    fi = hidpp_feature(dev, idx, 0x1000)
    if fi:
        r = hidpp_request(dev, idx, fi, 0)
        if r and r[0]:
            return r[0], r[2] in (1, 2, 3, 4)
    fi = hidpp_feature(dev, idx, 0x1001)
    if fi:
        r = hidpp_request(dev, idx, fi, 0)
        if r:
            return volt_to_pct(r[0] << 8 | r[1]), bool(r[2] & 0x80)
    return None


def logi_info(dev, idx):
    """(ชื่อ, ชนิด) จาก feature 0x0005 หรือ None ถ้าไม่มีอุปกรณ์ที่ index นี้"""
    fi = hidpp_feature(dev, idx, 0x0005, timeout=0.3)
    if not fi:
        return None
    r = hidpp_request(dev, idx, fi, 0)
    length = r[0] if r else 0
    name = b""
    while len(name) < length:
        r = hidpp_request(dev, idx, fi, 1, bytes([len(name)]))
        if not r:
            break
        name += r[:length - len(name)]
    r = hidpp_request(dev, idx, fi, 2)
    kind = LOGI_KINDS.get(r[0]) if r else None
    return name.decode("utf-8", "replace").strip("\0 ") or "Logitech", kind


def logi_open(path):
    dev = hid.device()
    dev.open_path(path)
    return dev


def logi_devices(cache):
    """หาอุปกรณ์ Logitech HID++ — ตัวรับ (index 1-6) และเสียบสาย/BT (index 0xFF)"""
    known = cache.setdefault("logi", {})
    paths = {f"{d['product_id']:04x}": d["path"] for d in hid.enumerate(LOGI_VID)
             if d["usage_page"] == 0xFF00 and d["usage"] == 0x0002}
    devices = []
    for pid, path in paths.items():
        if pid not in known:
            found = []
            try:
                dev = logi_open(path)
                try:
                    for idx in (0xFF, 1, 2, 3, 4, 5, 6):
                        info = logi_info(dev, idx)
                        if info:
                            found.append([idx, *info])
                finally:
                    dev.close()
            except OSError:
                continue
            if not found:
                continue  # อุปกรณ์หลับตอนค้นหา — ลองใหม่ด้วยเมนู "ค้นหาอุปกรณ์ใหม่"
            known[pid] = found
        for idx, name, kind in known[pid]:
            def read(path=path, idx=idx):
                try:
                    dev = logi_open(path)
                except OSError:
                    return None
                try:
                    return logi_battery(dev, idx)
                except OSError:
                    return None
                finally:
                    dev.close()
            devices.append({"key": f"logi:{pid}:{idx}", "kind": kind, "name": name, "read": read})
    return devices


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


# ---------- 4. Bluetooth ผ่าน Windows ----------

BT_PROP = "{104EA319-6EE2-4701-BD47-8DDBF425BBE5} 2"


def bt_batteries():
    """{ชื่ออุปกรณ์: %} จาก Windows"""
    ps = ("Get-PnpDevice -PresentOnly -Class Bluetooth,BTHLEDevice -EA 0 | ForEach-Object {"
          f"$b=(Get-PnpDeviceProperty -InstanceId $_.InstanceId -KeyName '{BT_PROP}' -EA 0).Data;"
          "if ($b -ne $null) { \"$($_.FriendlyName)`t$b\" } }")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True,
                             text=True, encoding="utf-8", timeout=60, creationflags=NO_WINDOW).stdout
    except (OSError, subprocess.TimeoutExpired):
        return {}
    res = {}
    for line in out.splitlines():
        name, _, pct = line.rpartition("\t")
        if name and pct.strip().isdigit():
            res[name] = int(pct)
    return res


def bt_devices():
    def read(name):
        v = bt_batteries().get(name)
        return (v, None) if v is not None else None
    return [{"key": "bt:" + n, "kind": None, "name": n, "read": lambda n=n: read(n)} for n in bt_batteries()]


# ---------- 5. อุปกรณ์ที่ไม่ส่งค่าแบต (แสดงแค่สถานะการเชื่อมต่อ) ----------

# ดองเกิลไม่ส่งค่าแบตมาที่คอม (ตรวจแล้ว: ไม่มีใน HID และโปรแกรมของผู้ผลิตก็ไม่มีฟีเจอร์แบต)
NO_BATTERY = {"040b:0897": ("หูฟัง SIGNO WP-601", "headset")}


def present_usb_keys():
    return {f"{d['vendor_id']:04x}:{d['product_id']:04x}" for d in hid.enumerate()}


def nobattery_devices(cache):
    """การ์ดสถานะการเชื่อมต่อ — แสดงเฉพาะรุ่นที่เคยเสียบในเครื่องนี้"""
    seen = cache.setdefault("seen_nobat", [])
    for key in present_usb_keys() & NO_BATTERY.keys():
        if key not in seen:
            seen.append(key)
    return [{"key": "usb:" + key, "kind": NO_BATTERY[key][1], "name": NO_BATTERY[key][0], "no_battery": True,
             "read": lambda: None, "connected": lambda k=key: k in present_usb_keys()}
            for key in seen if key in NO_BATTERY]


# ---------- อุปกรณ์ ----------

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


def discover(cache):
    """รวมอุปกรณ์จากทุกแหล่ง — คืนรายการ {key, kind, name, read}"""
    devices = []
    for source in (lambda: compx_devices(cache.setdefault("kinds", {})), lambda: logi_devices(cache),
                   headset_devices, bt_devices, lambda: nobattery_devices(cache)):
        try:
            devices += source()
        except Exception:  # แหล่งใดพังไม่ควรทำให้แหล่งอื่นหาย — แต่จดไว้ให้ไล่ปัญหาได้
            log_error("discover")
    return devices


# ---------- ไอคอน ----------

def level_color(pct):
    return (239, 68, 68) if pct <= 20 else (245, 158, 11) if pct <= 40 else (34, 197, 94)


def make_icon(res, stale=False):
    """ไอคอน 64px: ตัวเลข % ใหญ่ + แถบระดับแบตด้านล่าง + สายฟ้าถ้าชาร์จ"""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    ok = isinstance(res, (tuple, list))
    pct = res[0] if ok else 0
    text = str(pct) if ok else "--"
    font = ImageFont.truetype("segoeuib.ttf", 40 if len(text) >= 3 else 54)
    fill = (160, 160, 160) if stale else (255, 255, 255)
    d.text((32, 26), text, font=font, fill=fill, anchor="mm", stroke_width=2, stroke_fill=(0, 0, 0))
    d.rectangle((0, 54, 63, 63), fill=(70, 70, 70))
    if ok:
        color = (140, 140, 140) if stale else level_color(pct)
        d.rectangle((0, 54, max(6, 64 * pct // 100) - 1, 63), fill=color)
        if res[1]:
            d.polygon([(52, 0), (44, 14), (50, 14), (46, 26), (60, 10), (53, 10), (58, 0)], fill=(255, 220, 0))
    return img


def tooltip(name, res, eta=None):
    if not isinstance(res, (tuple, list)):
        return f"{name}: หลับอยู่ (ขยับ/กดปุ่มแล้วรีเฟรช)"
    return f"{name}: {res[0]}%" + (" กำลังชาร์จ" if res[1] else "") + (f" · เหลือ {eta}" if eta else "")


# ---------- ประวัติแบต + ประมาณเวลาที่เหลือ ----------

HISTORY_DAYS = 7
MIN_SPAN_H, MIN_DROP = 2, 3  # ต้องมีข้อมูลอย่างน้อย 2 ชม. และแบตลด ≥3% ถึงจะประมาณ (กันตัวเลขมั่ว)


def record_history(hist, ts, pct, charging):
    """เก็บ [ts, pct, charging] เมื่อค่าเปลี่ยน หรือทุก 30 นาที — เก็บย้อนหลัง 7 วัน"""
    if not hist or hist[-1][1] != pct or hist[-1][2] != bool(charging) or ts - hist[-1][0] >= 1800:
        hist.append([ts, pct, bool(charging)])
    cutoff = ts - HISTORY_DAYS * 86400
    while hist and hist[0][0] < cutoff:
        hist.pop(0)


def estimate_remaining_h(hist, now):
    """ชั่วโมงที่เหลือจากอัตราลดของช่วงคายประจุล่าสุด (ตั้งแต่ชาร์จครั้งก่อน) หรือ None ถ้าข้อมูลยังไม่พอ"""
    seg = []
    for ts, pct, chg in reversed(hist):
        if chg or (seg and pct < seg[-1][1]):  # เจอช่วงชาร์จ / แบตเพิ่มขึ้น = จบช่วงคายประจุ
            break
        seg.append((ts, pct))
    if len(seg) < 2:
        return None
    (t1, p1), (t0, p0) = seg[0], seg[-1]
    span_h, drop = (t1 - t0) / 3600, p0 - p1
    if span_h < MIN_SPAN_H or drop < MIN_DROP:
        return None
    return max(0.0, p1 / (drop / span_h) - (now - t1) / 3600)


def fmt_remaining(h):
    if h is None:
        return None
    if h < 1:
        return "ไม่ถึง 1 ชม."
    return f"~{round(h)} ชม." if h < 48 else f"~{round(h / 24)} วัน"


# ---------- ติดตั้งไว้ที่ถาวร ----------

INSTALL_DIR = Path(os.environ.get("LOCALAPPDATA", str(DATA_DIR))) / "BatteryTray"


def same_dir(a, b):
    """เทียบโฟลเดอร์ทั้งแบบตรงตัวและแบบตาม link/redirect — ตรงแบบใดแบบหนึ่งถือว่าเป็นที่เดียวกัน
    (resolve() อย่างเดียวพลาดได้ เช่น โปรเซสในแพ็กเกจ MSIX ที่ %LOCALAPPDATA% ถูก redirect)"""
    norm = lambda p: os.path.normcase(os.path.abspath(p))  # noqa: E731
    return norm(a) == norm(b) or norm(Path(a).resolve()) == norm(Path(b).resolve())


def needs_install():
    if not FROZEN or "--installed-from" in sys.argv:  # เพิ่งถูกติดตั้งมา — ห้ามติดตั้งซ้ำ (กันวนไม่รู้จบ)
        return False
    return not same_dir(Path(sys.executable).parent, INSTALL_DIR)


def install_copy(src, dest):
    """คัดลอก src ไปที่ dest (แทนตัวเดิมถ้ามี โดยคืนตัวเดิมถ้าล้มเหลว)"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        shutil.copy2(src, dest)
        return
    new = dest.with_name(dest.name + ".new")
    shutil.copy2(src, new)
    swap_exe(dest, new)


# ---------- ตั้งค่า ----------

STARTUP_LNK = Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs\Startup\Battery Tray.lnk"
DEFAULTS = {"interval": 60, "alert": 20, "hidden": [], "names": {}, "notify_full": True}


def launch_cmd():
    """คำสั่งเปิดแอปนี้แบบไม่มีหน้าต่าง console"""
    if FROZEN:
        return [sys.executable]
    return [str(Path(sys.executable).with_name("pythonw.exe")), str(Path(__file__).resolve())]


def relaunch_env():
    """env สำหรับเปิดตัวเองใหม่ — ตัวใหม่ต้องแตกไฟล์เอง ไม่ใช้โฟลเดอร์ชั่วคราวของตัวเก่า
    (ไม่งั้นพอตัวเก่าปิด โฟลเดอร์ถูกลบ → 'Failed to import encodings module' / หา USB ไม่เจอ)"""
    env = dict(os.environ)
    if FROZEN:
        env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


def set_startup(on, exe=None):
    if not on:
        STARTUP_LNK.unlink(missing_ok=True)
        return
    target, *args = [str(exe)] if exe else launch_cmd()
    ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:LNK);"
          "$s.TargetPath=$env:TARGET; $s.Arguments=$env:ARGS;"
          "$s.WorkingDirectory=$env:DIR; $s.Description='Battery Tray'; $s.Save()")
    env = dict(os.environ, LNK=str(STARTUP_LNK), TARGET=target, DIR=str(Path(exe).parent if exe else APP_DIR),
               ARGS=" ".join(f'"{a}"' for a in args))
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], env=env, creationflags=NO_WINDOW)


def work_area_height(root):
    """ความสูงจอที่ใช้ได้จริง (หัก taskbar) — fallback เป็นความสูงจอ"""
    try:
        import ctypes
        r = (ctypes.c_long * 4)()
        if ctypes.windll.user32.SystemParametersInfoW(0x30, 0, r, 0):  # SPI_GETWORKAREA
            return r[3] - r[1]
    except Exception:
        pass
    return root.winfo_screenheight()


def settings_window(devices, settings, last, on_save, history=None):
    """หน้าต่างตั้งค่า (customtkinter ใน thread ของตัวเอง)
    ดีไซน์: ui-ux-pro-max — Dark slate + status green, สถานะมีข้อความกำกับ (ไม่ใช้สีอย่างเดียว)"""
    import webbrowser

    import customtkinter as ctk

    C = {"bg": "#0F172A", "card": "#1B2336", "muted": "#272F42", "line": "#2B3548", "border": "#475569",
         "text": "#F8FAFC", "sub": "#94A3B8", "accent": "#22C55E", "on_accent": "#0F172A",
         "accent_hover": "#16A34A", "danger": "#EF4444"}
    TH = "Leelawadee UI"
    GLYPH = {"mouse": "", "keyboard": "", "headset": "", None: ""}  # Segoe MDL2 Assets

    def hexc(rgb):
        return "#%02x%02x%02x" % rgb

    def status_of(old, stale):
        """(ข้อความ, สี) — ข้อความกำกับเสมอ ไม่พึ่งสีอย่างเดียว"""
        if not old:
            return "ยังไม่ทราบค่า", C["sub"]
        pct, chg = old[0]
        if stale:
            return f"หลับอยู่ · ค่าล่าสุด {old[1]}", C["sub"]
        if chg:
            return "⚡ กำลังชาร์จ", C["accent"]
        if pct <= 20:
            return "วิกฤต · ควรชาร์จ", hexc(level_color(pct))
        if pct <= 40:
            return "ต่ำ", hexc(level_color(pct))
        return "ปกติ", hexc(level_color(pct))

    def focus_ring(entry):
        entry.bind("<FocusIn>", lambda _: entry.configure(border_color=C["accent"]))
        entry.bind("<FocusOut>", lambda _: entry.configure(border_color=C["card"]))

    ctk.set_appearance_mode("dark")
    root = ctk.CTk(fg_color=C["bg"])
    root.title("Battery Tray")
    root.resizable(False, False)
    root.attributes("-topmost", True)
    body = ctk.CTkFrame(root, fg_color=C["bg"])
    body.pack(padx=24, pady=16, fill="both")

    # ---- ส่วนหัว: ชื่อแอป + สรุปภาพรวม ----
    shown = [d for d in devices if d["key"] != "none"]
    known = [last[d["key"]][0][0] for d in shown if d["key"] in last]
    head = ctk.CTkFrame(body, fg_color="transparent")
    head.pack(fill="x")
    ctk.CTkLabel(head, text="Battery Tray", font=(TH, 24, "bold"), text_color=C["text"]).pack(side="left")
    ctk.CTkLabel(head, text=f"v{VERSION}", font=(TH, 12), text_color=C["sub"]).pack(side="left", padx=8, pady=(8, 0))
    summary = f"{len(shown)} อุปกรณ์" + (f"  ·  ต่ำสุด {min(known)}%" if known else "")
    ctk.CTkLabel(body, text=summary, font=(TH, 13), text_color=C["sub"]).pack(anchor="w", pady=(0, 10))

    # ---- การ์ดอุปกรณ์ ----
    rows = []
    if not shown:
        empty = ctk.CTkFrame(body, fg_color=C["card"], corner_radius=16)
        empty.pack(fill="x", pady=6)
        ctk.CTkLabel(empty, text="ยังไม่พบอุปกรณ์ที่รองรับ", font=(TH, 15, "bold"),
                     text_color=C["text"]).pack(anchor="w", padx=18, pady=(16, 2))
        ctk.CTkLabel(empty, text="เสียบดองเกิล เปิดอุปกรณ์ แล้วคลิกขวาที่ไอคอน → ค้นหาอุปกรณ์ใหม่",
                     font=(TH, 13), text_color=C["sub"]).pack(anchor="w", padx=18, pady=(0, 16))
    # ponytail: จำนวนการ์ดที่แสดงพร้อมกันประมาณจากความสูงจอ (ส่วนอื่นของหน้าต่าง ~600px, การ์ด ~128px)
    MAX_CARDS = max(1, (work_area_height(root) - 600) // 128)
    devlist = (ctk.CTkScrollableFrame(body, height=MAX_CARDS * 128, fg_color=C["bg"])
               if len(shown) > MAX_CARDS else ctk.CTkFrame(body, fg_color=C["bg"]))
    devlist.pack(fill="x")
    for dev in shown:
        if dev.get("no_battery"):
            connected = dev["connected"]()
            card = ctk.CTkFrame(devlist, fg_color=C["card"], corner_radius=16, border_width=1, border_color=C["line"])
            card.pack(fill="x", pady=4)
            card.grid_columnconfigure(1, weight=1)
            badge = ctk.CTkFrame(card, width=48, height=48, corner_radius=12, fg_color=C["muted"])
            badge.grid(row=0, column=0, rowspan=2, padx=(16, 12), pady=16)
            badge.grid_propagate(False)
            ctk.CTkLabel(badge, text=GLYPH.get(dev.get("kind"), GLYPH[None]), font=("Segoe MDL2 Assets", 20),
                         text_color=C["text"] if connected else C["sub"]).place(relx=0.5, rely=0.5, anchor="center")
            name = ctk.StringVar(value=settings["names"].get(dev["key"], dev["name"]))
            entry = ctk.CTkEntry(card, textvariable=name, font=(TH, 15, "bold"), text_color=C["text"],
                                 fg_color=C["card"], border_width=1, border_color=C["card"], corner_radius=8, height=32)
            entry.grid(row=0, column=1, sticky="ew", pady=(14, 0))
            focus_ring(entry)
            pill = ctk.CTkFrame(card, fg_color=C["muted"], corner_radius=10)
            pill.grid(row=1, column=1, sticky="w", padx=4, pady=(4, 14))
            ctk.CTkLabel(pill, text="● เชื่อมต่ออยู่ · รุ่นนี้ไม่ส่งค่าแบต" if connected else "○ ไม่ได้เสียบดองเกิล",
                         font=(TH, 12), text_color=C["accent"] if connected else C["sub"]).pack(padx=10, pady=1)
            ctk.CTkLabel(card, text="—", font=("Segoe UI", 30, "bold"),
                         text_color=C["sub"]).grid(row=0, column=2, rowspan=2, padx=(8, 16))
            rows.append((dev, None, name))
            continue
        old = last.get(dev["key"])
        stale = bool(dev.get("stale"))
        pct = old[0][0] if old else None
        status, scolor = status_of(old, stale)
        eta = fmt_remaining(estimate_remaining_h((history or {}).get(dev["key"], []), time.time()))
        if eta and old and not stale and not old[0][1]:
            status += f" · เหลือ {eta}"
        color = hexc(level_color(pct)) if pct is not None and not stale else C["sub"]

        card = ctk.CTkFrame(devlist, fg_color=C["card"], corner_radius=16, border_width=1, border_color=C["line"])
        card.pack(fill="x", pady=4)
        card.grid_columnconfigure(1, weight=1)

        badge = ctk.CTkFrame(card, width=48, height=48, corner_radius=12, fg_color=C["muted"])
        badge.grid(row=0, column=0, rowspan=2, padx=(16, 12), pady=(16, 8))
        badge.grid_propagate(False)
        ctk.CTkLabel(badge, text=GLYPH.get(dev.get("kind"), GLYPH[None]), font=("Segoe MDL2 Assets", 20),
                     text_color=color).place(relx=0.5, rely=0.5, anchor="center")

        name = ctk.StringVar(value=settings["names"].get(dev["key"], dev["name"]))
        entry = ctk.CTkEntry(card, textvariable=name, font=(TH, 15, "bold"), text_color=C["text"],
                             fg_color=C["card"], border_width=1, border_color=C["card"], corner_radius=8, height=32)
        entry.grid(row=0, column=1, sticky="ew", pady=(14, 0))
        focus_ring(entry)
        pill = ctk.CTkFrame(card, fg_color=C["muted"], corner_radius=10)
        pill.grid(row=1, column=1, sticky="w", padx=4, pady=(4, 0))
        ctk.CTkLabel(pill, text=status, font=(TH, 12), text_color=scolor).pack(padx=10, pady=1)

        ctk.CTkLabel(card, text=f"{pct}%" if pct is not None else "--", font=("Segoe UI", 30, "bold"),
                     text_color=color).grid(row=0, column=2, rowspan=2, padx=(8, 16))

        bar = ctk.CTkProgressBar(card, height=8, corner_radius=4, fg_color=C["muted"], progress_color=color)
        bar.set((pct or 0) / 100)
        bar.grid(row=2, column=0, columnspan=2, sticky="ew", padx=(16, 12), pady=(10, 14))

        show = ctk.BooleanVar(value=dev["key"] not in settings["hidden"])
        ctk.CTkSwitch(card, text="แสดงบนแถบงาน", variable=show, font=(TH, 12), text_color=C["sub"],
                      progress_color=C["accent"], button_color=C["text"], fg_color=C["border"],
                      width=40).grid(row=2, column=2, sticky="e", padx=(0, 16), pady=(10, 14))
        rows.append((dev, show, name))

    # ---- ตั้งค่าทั่วไป ----
    ctk.CTkLabel(body, text="การตั้งค่า", font=(TH, 14, "bold"), text_color=C["text"]).pack(anchor="w", pady=(12, 6))
    gen = ctk.CTkFrame(body, fg_color=C["card"], corner_radius=16, border_width=1, border_color=C["line"])
    gen.pack(fill="x")
    gen.grid_columnconfigure(0, weight=1)

    def row_label(r, title, sub):
        f = ctk.CTkFrame(gen, fg_color="transparent")
        f.grid(row=r, column=0, sticky="w", padx=18, pady=8)
        ctk.CTkLabel(f, text=title, font=(TH, 14, "bold"), text_color=C["text"]).pack(anchor="w")
        ctk.CTkLabel(f, text=sub, font=(TH, 12), text_color=C["sub"]).pack(anchor="w")

    def divider(r):
        ctk.CTkFrame(gen, height=1, fg_color=C["line"]).grid(row=r, column=0, columnspan=2, sticky="ew", padx=18)

    def segmented(r, options, current):
        var = ctk.StringVar(value=next((k for k, v in options.items() if v == current), next(iter(options))))
        ctk.CTkSegmentedButton(gen, values=list(options), variable=var, font=(TH, 12), height=32,
                               selected_color=C["accent"], selected_hover_color=C["accent_hover"],
                               unselected_color=C["muted"], unselected_hover_color=C["line"],
                               fg_color=C["muted"], text_color=C["text"]).grid(row=r, column=1, padx=18, sticky="e")
        return var

    intervals = {"30 วิ": 30, "1 นาที": 60, "5 นาที": 300, "15 นาที": 900}
    alerts = {"ปิด": 0, "10%": 10, "20%": 20, "30%": 30}
    row_label(0, "เปิดพร้อม Windows", "เริ่มทำงานเองทุกครั้งที่เปิดเครื่อง")
    startup = ctk.BooleanVar(value=STARTUP_LNK.exists())
    ctk.CTkSwitch(gen, text="", variable=startup, width=40, progress_color=C["accent"], button_color=C["text"],
                  fg_color=C["border"]).grid(row=0, column=1, padx=18, sticky="e")
    divider(1)
    row_label(2, "อัปเดตค่าทุก", "ถี่ขึ้น = เห็นค่าใหม่เร็วขึ้น")
    interval = segmented(2, intervals, settings["interval"])
    divider(3)
    row_label(4, "แจ้งเตือนแบตต่ำ", "เด้งแจ้งเตือนครั้งเดียวเมื่อแบตต่ำกว่าค่านี้")
    alert = segmented(4, alerts, settings["alert"])
    divider(5)
    row_label(6, "แจ้งเตือนชาร์จเต็ม", "สำหรับอุปกรณ์ที่บอกสถานะการชาร์จ")
    notify_full = ctk.BooleanVar(value=settings.get("notify_full", True))
    ctk.CTkSwitch(gen, text="", variable=notify_full, width=40, progress_color=C["accent"], button_color=C["text"],
                  fg_color=C["border"]).grid(row=6, column=1, padx=18, sticky="e")

    if not headsetcontrol_exe():
        hint = ctk.CTkLabel(body, text="ใช้หูฟัง SteelSeries / Corsair / HyperX?  ดาวน์โหลด HeadsetControl ↗",
                            font=(TH, 12), text_color=C["accent"], cursor="hand2")
        hint.pack(anchor="w", pady=(8, 0))
        hint.bind("<Button-1>", lambda _: webbrowser.open(HEADSETCONTROL_URL))

    msg = ctk.CTkLabel(body, text="", font=(TH, 12), text_color=C["danger"])  # pack เมื่อมี error เท่านั้น

    def save(*_):
        switches = [show for _, show, _ in rows if show is not None]
        if switches and not any(v.get() for v in switches):
            msg.configure(text="⚠ ต้องแสดงอย่างน้อย 1 อุปกรณ์ ไม่งั้นจะกลับมาเปิดหน้านี้ไม่ได้")
            msg.pack(anchor="w", pady=(4, 0), before=bar)
            return
        settings["hidden"] = [d["key"] for d, show, _ in rows if show is not None and not show.get()]
        settings["names"] = {d["key"]: n.get().strip() for d, _, n in rows
                             if n.get().strip() and n.get().strip() != d["name"]}
        settings["interval"] = intervals[interval.get()]
        settings["alert"] = alerts[alert.get()]
        settings["notify_full"] = notify_full.get()
        if startup.get() != STARTUP_LNK.exists():
            set_startup(startup.get())
        root.destroy()
        on_save()

    bar = ctk.CTkFrame(body, fg_color="transparent")
    bar.pack(fill="x", pady=(12, 0))
    ctk.CTkButton(bar, text="บันทึก", font=(TH, 14, "bold"), height=42, width=120, corner_radius=10,
                  fg_color=C["accent"], hover_color=C["accent_hover"], text_color=C["on_accent"],
                  cursor="hand2", command=save).pack(side="right")
    ctk.CTkButton(bar, text="ยกเลิก", font=(TH, 14), height=42, width=100, corner_radius=10, fg_color="transparent",
                  border_width=1, border_color=C["border"], hover_color=C["muted"], text_color=C["text"],
                  cursor="hand2", command=root.destroy).pack(side="right", padx=(0, 10))
    root.bind("<Return>", save)
    root.bind("<Escape>", lambda _: root.destroy())

    def center():
        root.update_idletasks()
        w, h = root.winfo_reqwidth(), root.winfo_reqheight()
        root.geometry(f"+{max(0, (root.winfo_screenwidth() - w) // 2)}+{max(0, (work_area_height(root) - h) // 2)}")
    root.after(10, center)
    root.mainloop()


# ---------- แอป ----------

MUTEX_NAME = "Local\\BatteryTray.SingleInstance"
WAIT_FLAG = "--wait-previous"  # เปิดตัวเองใหม่ (อัปเดต/ค้นหาใหม่/ติดตั้ง) — รอตัวเก่าปิดแทนการถูกบล็อก
_mutex = None  # ถือไว้ตลอดอายุโปรเซส; Windows ปล่อยให้เองตอนปิด (แม้โปรเซสตาย)


def acquire_single_instance(wait_s=0, name=MUTEX_NAME):
    """True ถ้าเป็นตัวเดียวในเครื่อง (named mutex ของ Windows — ไม่ขึ้นกับจังหวะเวลา)"""
    global _mutex
    import ctypes
    k = ctypes.windll.kernel32
    k.CreateMutexW.restype = ctypes.c_void_p
    handle = k.CreateMutexW(None, False, name)
    if not handle:
        return True  # สร้างไม่ได้ — ไม่บล็อกการใช้งาน
    r = k.WaitForSingleObject(ctypes.c_void_p(handle), int(wait_s * 1000))
    if r in (0, 0x80):  # WAIT_OBJECT_0 / WAIT_ABANDONED (ตัวเก่าตายโดยไม่ปล่อย)
        _mutex = handle
        return True
    k.CloseHandle(ctypes.c_void_p(handle))
    return False


def relaunch(cmd, cwd, *args):
    """เปิดตัวเองใหม่ — ตัวใหม่จะรอ mutex จนตัวนี้ปิด"""
    subprocess.Popen([*cmd, *args, WAIT_FLAG], cwd=cwd, env=relaunch_env())


def self_install():
    """เปิดจากที่อื่น (เช่น Downloads) → คัดลอกไป INSTALL_DIR, ตั้งเปิดพร้อม Windows, เปิดตัวนั้นแทน
    คืน True ถ้าตัวนี้ควรปิด (ส่งต่อให้ตัวที่ติดตั้งแล้ว)"""
    dest = INSTALL_DIR / EXE_NAME
    try:
        install_copy(Path(sys.executable), dest)
        set_startup(True, exe=dest)
        relaunch([str(dest)], dest.parent, "--installed-from", sys.executable)
        return True
    except Exception:
        log_error("self-install")
        return False  # ใช้งานต่อจากที่เดิม


def app():
    if not acquire_single_instance(wait_s=20 if WAIT_FLAG in sys.argv else 0):
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, "Battery Tray เปิดอยู่แล้ว — ดูที่ไอคอน % ข้างนาฬิกา\n"
                                         "(ถ้าไม่เห็น ให้กดลูกศร ^ บนแถบงาน)", "Battery Tray", 0x40)
        return
    if needs_install():
        cleanup_old_exe()  # อัปเดตจาก v1.4.x ที่ Downloads ทิ้ง .old ไว้ — ลบก่อนย้ายไปที่ถาวร
        if self_install():
            return
    installed_from = sys.argv[sys.argv.index("--installed-from") + 1] if "--installed-from" in sys.argv else None
    threading.Thread(target=cleanup_old_exe, daemon=True).start()
    cache = load_cache()
    first_run = "settings" not in cache
    settings = {**DEFAULTS, **cache.get("settings", {})}
    cache["settings"] = settings
    last = cache.setdefault("last", {})
    all_devices = discover(cache)
    devices = [d for d in all_devices if not d.get("no_battery")] or [
        {"key": "none", "kind": None, "name": "ไม่พบอุปกรณ์ที่รองรับ", "read": lambda: None}]
    save_cache(cache)
    stop, wake, lock, settings_open = threading.Event(), threading.Event(), threading.Lock(), threading.Lock()
    alerted, full_notified = set(), set()
    history = cache.setdefault("history", {})
    icons = []

    def label(dev):
        return settings["names"].get(dev["key"], dev["name"])

    def refresh():
        with lock:
            for dev, icon in zip(devices, icons):
                icon.visible = dev["key"] not in settings["hidden"]
                try:
                    res = dev["read"]()
                except Exception:
                    log_error(f"read {dev['key']}")
                    res = None
                name = label(dev)
                if res:
                    dev["stale"] = False
                    prev = last.get(dev["key"])
                    last[dev["key"]] = [list(res), time.strftime("%d/%m %H:%M")]
                    hist = history.setdefault(dev["key"], [])
                    record_history(hist, time.time(), res[0], res[1])
                    eta = None if res[1] else fmt_remaining(estimate_remaining_h(hist, time.time()))
                    icon.icon, icon.title = make_icon(res), tooltip(name, res, eta)
                    was_charging = bool(prev and prev[0][1])
                    full = res[0] >= 100 and (res[1] or was_charging)
                    if full and dev["key"] not in full_notified:
                        if settings.get("notify_full", True):
                            icon.notify(f"{name} ชาร์จเต็มแล้ว — ถอดสายได้เลย", "ชาร์จเต็ม")
                        full_notified.add(dev["key"])
                    elif not res[1] and res[0] < 100:
                        full_notified.discard(dev["key"])
                    low = bool(settings["alert"]) and res[0] <= settings["alert"] and not res[1]
                    if low and dev["key"] not in alerted:
                        icon.notify(f"{name} เหลือ {res[0]}% — ควรชาร์จ", "แบตใกล้หมด")
                        alerted.add(dev["key"])
                    elif not low:
                        alerted.discard(dev["key"])
                elif dev["key"] in last:
                    dev["stale"] = True
                    old, at = last[dev["key"]]
                    icon.icon = make_icon(old, stale=True)
                    icon.title = f"{name}: {old[0]}% (ค่าล่าสุด {at}, ตอนนี้หลับอยู่)"
                else:
                    icon.icon, icon.title = make_icon(None), tooltip(name, None)
            save_cache(cache)

    def open_settings(*_):
        if not settings_open.acquire(blocking=False):
            return  # เปิดอยู่แล้ว

        def run():
            try:
                settings_window(all_devices, settings, last, on_save=wake.set, history=history)
            finally:
                settings_open.release()
        threading.Thread(target=run, daemon=True).start()

    def quit_all(*_):
        stop.set()
        wake.set()
        for icon in icons:
            icon.stop()

    def rescan(*_):
        # ponytail: เริ่มโปรเซสใหม่แทนการเพิ่ม/ลบไอคอนสด ๆ
        cache.pop("kinds", None)
        cache.pop("logi", None)
        save_cache(cache)
        relaunch(launch_cmd(), APP_DIR)
        quit_all()

    update = {}

    def check_update(manual=False):
        if not manual and time.time() - cache.get("update_checked", 0) < UPDATE_EVERY_S:
            return
        cache["update_checked"] = time.time()
        save_cache(cache)
        rel = latest_release()
        if not rel:
            if manual:
                icons[0].notify("เช็คอัปเดตไม่ได้ — ตรวจการเชื่อมต่ออินเทอร์เน็ตแล้วลองใหม่", "เช็คอัปเดต")
            return
        if not is_newer(rel["tag"], VERSION):
            if manual:
                icons[0].notify(f"ใช้เวอร์ชันล่าสุดแล้ว (v{VERSION})", "เช็คอัปเดต")
            return
        update.update(rel)
        for icon in icons:
            icon.update_menu()
        if manual or cache.get("update_notified") != rel["tag"]:
            cache["update_notified"] = rel["tag"]
            save_cache(cache)
            icons[0].notify(f"Battery Tray {rel['tag']} พร้อมแล้ว — คลิกขวาที่ไอคอน → {update_label()}", "มีเวอร์ชันใหม่")

    def can_self_update():
        return FROZEN and bool(update.get("asset_url")) and isinstance(update.get("asset_size"), int)

    def update_label(*_):
        verb = "อัปเดตเป็น" if can_self_update() else "ดาวน์โหลด"
        return f"{verb} {update.get('tag')} ตอนนี้" if can_self_update() else f"{verb}เวอร์ชันใหม่ ({update.get('tag')})"

    def open_release_page():
        import webbrowser
        webbrowser.open(update.get("url", RELEASES_PAGE))

    def run_update():
        target = Path(sys.executable)
        new = target.with_name(target.name + ".new")
        try:
            icons[0].notify(f"กำลังดาวน์โหลด {update['tag']}...", "กำลังอัปเดต")
            download_update(update["asset_url"], update["asset_size"], new)
            swap_exe(target, new)
        except Exception:
            log_error("self-update")
            new.unlink(missing_ok=True)
            icons[0].notify("อัปเดตอัตโนมัติไม่สำเร็จ — เปิดหน้าดาวน์โหลดให้แล้ว", "อัปเดตไม่สำเร็จ")
            open_release_page()
            return
        relaunch([str(target)], target.parent)
        quit_all()

    def on_update(*_):
        if can_self_update():
            threading.Thread(target=run_update, daemon=True).start()
        else:
            open_release_page()

    menu = pystray.Menu(pystray.MenuItem(update_label, on_update, visible=lambda _: bool(update)),
                        pystray.MenuItem("ตั้งค่า...", open_settings, default=True),
                        pystray.MenuItem("รีเฟรช", lambda *_: wake.set()),
                        pystray.MenuItem("ค้นหาอุปกรณ์ใหม่", rescan),
                        pystray.MenuItem("เช็คอัปเดต",
                                         lambda *_: threading.Thread(target=check_update, args=(True,), daemon=True).start()),
                        pystray.Menu.SEPARATOR,
                        pystray.MenuItem("ปิด", quit_all))
    for dev in devices:
        old = last.get(dev["key"])
        start = make_icon(old[0], stale=True) if old else make_icon(None)
        icons.append(pystray.Icon("battery_" + dev["key"], start, label(dev), menu))
    for icon in icons[1:]:
        icon.run_detached()

    def loop():
        nonlocal installed_from
        show_first = first_run
        while not stop.is_set():
            refresh()
            check_update()
            if show_first:
                show_first = False
                open_settings()
            if installed_from:
                icons[0].notify(f"ติดตั้งไว้ที่ {INSTALL_DIR} และตั้งให้เปิดพร้อม Windows แล้ว — "
                                f"ลบไฟล์เดิม ({Path(installed_from).name} ใน {Path(installed_from).parent.name}) ได้เลย",
                                "ติดตั้งเรียบร้อย")
                installed_from = None
            wake.wait(settings["interval"])
            wake.clear()

    threading.Thread(target=loop, daemon=True).start()
    icons[0].run()


def test():
    assert is_newer("v1.2.0", "1.1.0") and is_newer("v1.10.0", "1.9.0")
    assert not is_newer("v1.1.0", "1.1.0") and not is_newer("v1.0.0", "1.1.0") and not is_newer("beta", "1.1.0")

    # ประมาณเวลาที่เหลือ: ข้อมูลน้อย/ช่วงชาร์จ → None
    H = 3600
    hist = []
    for i, p in enumerate([80, 78, 76, 74, 72, 70]):  # ลด 2% ทุก 24 นาที = 5%/ชม. รวม 2 ชม.
        record_history(hist, 1000 + i * 1440, p, False)
    assert round(estimate_remaining_h(hist, 1000 + 5 * 1440), 1) == 14.0  # 70% / 5%/ชม.
    assert round(estimate_remaining_h(hist, 1000 + 5 * 1440 + 4 * H), 1) == 10.0  # ผ่านไปอีก 4 ชม.
    assert estimate_remaining_h(hist[:3], 1000 + 2 * 1440) is None       # ยังไม่ถึง 2 ชม.
    hist2 = [[0, 90, False], [2 * H, 80, False], [3 * H, 60, True], [3 * H + 60, 85, False]]
    assert estimate_remaining_h(hist2, 3 * H + 60) is None               # เพิ่งชาร์จ เริ่มนับใหม่
    hist3 = [[0, 50, False], [H, 40, False], [2 * H, 70, False], [5 * H, 64, False]]
    assert round(estimate_remaining_h(hist3, 5 * H)) == 32               # ใช้เฉพาะช่วงหลังแบตเพิ่ม: 2%/ชม.
    assert fmt_remaining(0.5) == "ไม่ถึง 1 ชม." and fmt_remaining(7.4) == "~7 ชม." and fmt_remaining(72) == "~3 วัน"
    old_hist = []
    record_history(old_hist, 0, 50, False)
    record_history(old_hist, 8 * 86400, 49, False)
    assert len(old_hist) == 1                                            # เก่ากว่า 7 วันถูกลบ
    rh = []
    record_history(rh, 0, 50, False)
    record_history(rh, 60, 50, False)
    assert len(rh) == 1                                                  # ค่าไม่เปลี่ยน ไม่เก็บซ้ำทุกนาที

    # ติดตั้งไว้ที่ถาวร: คัดลอกใหม่ / แทนตัวเดิม; ไม่ติดตั้งตอนรันจากซอร์ส
    import tempfile
    assert not needs_install()
    assert same_dir("C:\\Users\\X\\AppData\\Local\\BatteryTray", "c:\\users\\x\\appdata\\local\\batterytray\\")
    assert not same_dir("C:\\Users\\X\\Downloads", "C:\\Users\\X\\AppData\\Local\\BatteryTray")
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        src = d / "Downloads" / EXE_NAME
        src.parent.mkdir()
        src.write_bytes(b"MZ v2")
        dest = d / "Install" / EXE_NAME
        install_copy(src, dest)
        assert dest.read_bytes() == b"MZ v2"
        src.write_bytes(b"MZ v3")
        install_copy(src, dest)
        assert dest.read_bytes() == b"MZ v3"

    # กันเปิดซ้ำ: ตัวแรกได้ mutex, โปรเซสอื่นที่ขอชื่อเดียวกันต้องถูกปฏิเสธ
    name = f"Local\\BatteryTray.Test.{os.getpid()}"
    assert acquire_single_instance(0, name)
    probe = ("import sys; sys.path.insert(0, %r); import battery_monitor as b; "
             "print(b.acquire_single_instance(0, %r))" % (str(Path(__file__).resolve().parent), name))
    out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, timeout=60).stdout.strip()
    assert out.endswith("False"), out

    # อัปเดตตัวเอง: สลับไฟล์ได้, ถ้าวางไฟล์ใหม่ไม่ได้ต้องคืนตัวเดิม, ไฟล์โหลดไม่ครบต้องถูกปฏิเสธ
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        target, new = d / EXE_NAME, d / (EXE_NAME + ".new")
        target.write_bytes(b"MZ old")
        new.write_bytes(b"MZ new")
        swap_exe(target, new)
        assert target.read_bytes() == b"MZ new" and (d / (EXE_NAME + ".old")).read_bytes() == b"MZ old"
        target.write_bytes(b"MZ cur")
        try:
            swap_exe(target, d / "missing.exe")
        except OSError:
            pass
        assert target.read_bytes() == b"MZ cur"
        src = d / "src.exe"
        src.write_bytes(b"MZ" + b"x" * 10)
        download_update(src.as_uri(), 12, d / "ok.exe")
        assert (d / "ok.exe").read_bytes()[:2] == b"MZ"
        for bad_size in (11, 13):
            try:
                download_update(src.as_uri(), bad_size, d / "bad.exe")
                raise AssertionError("ขนาดไม่ตรงต้องถูกปฏิเสธ")
            except ValueError:
                assert not (d / "bad.exe").exists() and not (d / "bad.exe.part").exists()

    # อุปกรณ์ไม่ส่งค่าแบต: ขึ้นเมื่อเคยเสียบ, บอกสถานะเสียบ/ถอดถูกต้อง
    global present_usb_keys
    real_present = present_usb_keys
    try:
        present_usb_keys = lambda: set()  # noqa: E731
        assert nobattery_devices({}) == []
        present_usb_keys = lambda: {"040b:0897", "3554:f58e"}  # noqa: E731
        c = {}
        (hs,) = nobattery_devices(c)
        assert hs["kind"] == "headset" and hs["connected"]() and c["seen_nobat"] == ["040b:0897"]
        present_usb_keys = lambda: set()  # noqa: E731
        (hs,) = nobattery_devices(c)
        assert not hs["connected"]()
    finally:
        present_usb_keys = real_present

    # Compx: คำตอบจริงจาก capture / อุปกรณ์
    assert mouse_frame().hex() == "0804000000000000000000000000000049"
    assert mouse_parse(bytes.fromhex("0804000000026400104c00000000000087")) == (100, False)
    assert mouse_parse(bytes.fromhex("0804010000000000000000000000000048")) is None
    assert kb_frame().hex() == "134a01000000000000000000000000000000005e"
    assert kb_parse(bytes.fromhex("134a0100025201000000000000000000000000b3")) == (82, None)

    # Logitech: จำลองอุปกรณ์ HID++ ที่ index 1 มี 0x1004 อยู่ที่ feature index 0x08
    class FakeLogi:
        def __init__(self):
            self.out = []

        def write(self, p):
            idx, feat, fnsw = p[1], p[2], p[3]
            if idx != 1:
                self.out.append(bytes([0x10, idx, 0x8F, feat, fnsw, 0x09, 0]))
            elif feat == 0 and p[4:6] == b"\x10\x04":
                self.out.append(bytes([0x11, 1, 0, fnsw, 0x08]).ljust(20, b"\0"))
            elif feat == 0:
                self.out.append(bytes([0x11, 1, 0, fnsw, 0x00]).ljust(20, b"\0"))
            elif feat == 0x08:
                self.out.append(bytes([0x11, 1, 0x08, fnsw, 57, 0x04, 0x01]).ljust(20, b"\0"))
            return len(p)

        def read(self, n, t):
            return list(self.out.pop(0)) if self.out else []

    fake = FakeLogi()
    assert logi_battery(fake, 1) == (57, True)
    assert logi_battery(fake, 2) is None
    assert volt_to_pct(4200) == 100 and volt_to_pct(3800) == 50 and volt_to_pct(3300) == 0

    # HeadsetControl: รูปแบบ JSON ของ headsetcontrol -o json
    hc = headsetcontrol_parse(json.dumps({"devices": [
        {"device": "SteelSeries Arctis 7", "id_vendor": "0x1038", "id_product": "0x12ad",
         "battery": {"status": "BATTERY_CHARGING", "level": 64}},
        {"device": "HyperX Cloud", "id_vendor": "0x0951", "id_product": "0x16c4",
         "battery": {"status": "BATTERY_UNAVAILABLE", "level": -1}}]}))
    assert hc["hc:0x1038:0x12ad"] == ("SteelSeries Arctis 7", (64, True))
    assert hc["hc:0x0951:0x16c4"] == ("HyperX Cloud", None)
    assert headsetcontrol_parse("not json") == {}

    sys.stdout.reconfigure(encoding="utf-8")
    for dev in discover(load_cache()):
        if dev.get("no_battery"):
            print(f"{dev['name']}: " + ("เชื่อมต่ออยู่ (ไม่ส่งค่าแบต)" if dev["connected"]() else "ไม่ได้เสียบ"))
            continue
        print(tooltip(dev["name"], dev["read"]()))


if __name__ == "__main__":
    test() if "--test" in sys.argv else app()
