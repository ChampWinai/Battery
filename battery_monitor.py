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


def save_cache(cache):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


def discover(cache):
    """รวมอุปกรณ์จากทุกแหล่ง — คืนรายการ {key, kind, name, read}"""
    devices = []
    for source in (lambda: compx_devices(cache.setdefault("kinds", {})), lambda: logi_devices(cache),
                   headset_devices, bt_devices):
        try:
            devices += source()
        except Exception:  # แหล่งใดพังไม่ควรทำให้แหล่งอื่นหาย
            pass
    return devices


# ---------- ไอคอน ----------

def level_color(pct):
    return (230, 60, 60) if pct <= 20 else (245, 160, 30) if pct <= 40 else (70, 200, 110)


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


def tooltip(name, res):
    if not isinstance(res, (tuple, list)):
        return f"{name}: หลับอยู่ (ขยับ/กดปุ่มแล้วรีเฟรช)"
    return f"{name}: {res[0]}%" + (" กำลังชาร์จ" if res[1] else "")


# ---------- ตั้งค่า ----------

STARTUP_LNK = Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs\Startup\Battery Tray.lnk"
DEFAULTS = {"interval": 60, "alert": 20, "hidden": [], "names": {}}


def launch_cmd():
    """คำสั่งเปิดแอปนี้แบบไม่มีหน้าต่าง console"""
    if FROZEN:
        return [sys.executable]
    return [str(Path(sys.executable).with_name("pythonw.exe")), str(Path(__file__).resolve())]


def set_startup(on):
    if not on:
        STARTUP_LNK.unlink(missing_ok=True)
        return
    target, *args = launch_cmd()
    ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:LNK);"
          "$s.TargetPath=$env:TARGET; $s.Arguments=$env:ARGS;"
          "$s.WorkingDirectory=$env:DIR; $s.Description='Battery Tray'; $s.Save()")
    env = dict(os.environ, LNK=str(STARTUP_LNK), TARGET=target, DIR=str(APP_DIR),
               ARGS=" ".join(f'"{a}"' for a in args))
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], env=env, creationflags=NO_WINDOW)


def settings_window(devices, settings, last, on_save):
    """หน้าต่างตั้งค่า (customtkinter ใน thread ของตัวเอง)"""
    import webbrowser

    import customtkinter as ctk

    BG, CARD, LINE = "#0e1014", "#171a21", "#232733"
    TEXT, MUTED, ACCENT = "#eef0f4", "#8a90a0", "#4f8cff"
    TH = "Leelawadee UI"
    GLYPH = {"mouse": "", "keyboard": "", "headset": "", None: ""}  # Segoe MDL2 Assets

    ctk.set_appearance_mode("dark")
    root = ctk.CTk(fg_color=BG)
    root.title("Battery Tray")
    root.resizable(False, False)
    root.attributes("-topmost", True)
    body = ctk.CTkFrame(root, fg_color=BG)
    body.pack(padx=22, pady=20, fill="both")

    ctk.CTkLabel(body, text="Battery Tray", font=(TH, 22, "bold"), text_color=TEXT).pack(anchor="w")
    ctk.CTkLabel(body, text="แบตเตอรี่อุปกรณ์ไร้สายของคุณ", font=(TH, 12), text_color=MUTED).pack(anchor="w", pady=(0, 14))

    rows = []
    if not [d for d in devices if d["key"] != "none"]:
        ctk.CTkLabel(body, text="ยังไม่พบอุปกรณ์ที่รองรับ\nเสียบดองเกิล เปิดอุปกรณ์ แล้วคลิกขวาที่ไอคอน → ค้นหาอุปกรณ์ใหม่",
                     font=(TH, 13), text_color=MUTED, justify="left").pack(anchor="w", pady=8)
    for dev in devices:
        if dev["key"] == "none":
            continue
        old = last.get(dev["key"])
        pct = old[0][0] if old else None
        color = "#%02x%02x%02x" % level_color(pct) if pct is not None else MUTED

        card = ctk.CTkFrame(body, fg_color=CARD, corner_radius=16, border_width=1, border_color=LINE)
        card.pack(fill="x", pady=5)
        card.grid_columnconfigure(1, weight=1)

        badge = ctk.CTkFrame(card, width=46, height=46, corner_radius=12, fg_color=LINE)
        badge.grid(row=0, column=0, rowspan=2, padx=(14, 12), pady=14)
        badge.grid_propagate(False)
        ctk.CTkLabel(badge, text=GLYPH.get(dev.get("kind"), GLYPH[None]), font=("Segoe MDL2 Assets", 20),
                     text_color=color).place(relx=0.5, rely=0.5, anchor="center")

        name = ctk.StringVar(value=settings["names"].get(dev["key"], dev["name"]))
        ctk.CTkEntry(card, textvariable=name, font=(TH, 14, "bold"), text_color=TEXT, fg_color=CARD,
                     border_width=0, height=28).grid(row=0, column=1, sticky="ew", pady=(12, 0))
        status = f"อัปเดต {old[1]}" if old else "ยังไม่ทราบค่า — ขยับ/กดปุ่มอุปกรณ์"
        if old and old[0][1]:
            status += "  ·  ⚡ กำลังชาร์จ"
        ctk.CTkLabel(card, text=status, font=(TH, 12), text_color=MUTED).grid(row=1, column=1, sticky="w", padx=6)

        ctk.CTkLabel(card, text=f"{pct}%" if pct is not None else "--", font=("Segoe UI", 26, "bold"),
                     text_color=color).grid(row=0, column=2, rowspan=2, padx=(8, 6))
        show = ctk.BooleanVar(value=dev["key"] not in settings["hidden"])
        ctk.CTkSwitch(card, text="", variable=show, width=46, progress_color=ACCENT).grid(row=0, column=3, rowspan=2, padx=(4, 10))

        bar = ctk.CTkProgressBar(card, height=6, corner_radius=3, fg_color=LINE, progress_color=color)
        bar.set((pct or 0) / 100)
        bar.grid(row=2, column=0, columnspan=4, sticky="ew", padx=14, pady=(0, 14))
        rows.append((dev, show, name))

    gen = ctk.CTkFrame(body, fg_color=CARD, corner_radius=16, border_width=1, border_color=LINE)
    gen.pack(fill="x", pady=(14, 0))
    gen.grid_columnconfigure(0, weight=1)

    def row_label(r, title, sub):
        f = ctk.CTkFrame(gen, fg_color="transparent")
        f.grid(row=r, column=0, sticky="w", padx=16, pady=10)
        ctk.CTkLabel(f, text=title, font=(TH, 13, "bold"), text_color=TEXT).pack(anchor="w")
        ctk.CTkLabel(f, text=sub, font=(TH, 12), text_color=MUTED).pack(anchor="w")

    def segmented(r, options, current):
        var = ctk.StringVar(value=next((k for k, v in options.items() if v == current), next(iter(options))))
        ctk.CTkSegmentedButton(gen, values=list(options), variable=var, font=(TH, 12),
                               selected_color=ACCENT, selected_hover_color="#3b74e0",
                               unselected_color=LINE, fg_color=LINE).grid(row=r, column=1, padx=16, sticky="e")
        return var

    intervals = {"30 วิ": 30, "1 นาที": 60, "5 นาที": 300, "15 นาที": 900}
    alerts = {"ปิด": 0, "10%": 10, "20%": 20, "30%": 30}
    row_label(0, "เปิดพร้อม Windows", "เริ่มทำงานเองทุกครั้งที่เปิดเครื่อง")
    startup = ctk.BooleanVar(value=STARTUP_LNK.exists())
    ctk.CTkSwitch(gen, text="", variable=startup, width=46, progress_color=ACCENT).grid(row=0, column=1, padx=16, sticky="e")
    row_label(1, "อัปเดตค่าทุก", "ถี่ขึ้น = เห็นค่าใหม่เร็วขึ้น")
    interval = segmented(1, intervals, settings["interval"])
    row_label(2, "แจ้งเตือนแบตต่ำ", "เด้งแจ้งเตือนครั้งเดียวเมื่อแบตต่ำกว่าค่านี้")
    alert = segmented(2, alerts, settings["alert"])

    if not headsetcontrol_exe():
        hint = ctk.CTkLabel(body, text="หูฟัง SteelSeries / Corsair / HyperX / Logitech?  วาง headsetcontrol.exe "
                                       "ไว้ข้างโปรแกรมนี้ แล้วค้นหาอุปกรณ์ใหม่  ↗",
                            font=(TH, 12), text_color=ACCENT, cursor="hand2", wraplength=420, justify="left")
        hint.pack(anchor="w", pady=(10, 0))
        hint.bind("<Button-1>", lambda _: webbrowser.open(HEADSETCONTROL_URL))

    msg = ctk.CTkLabel(body, text="", font=(TH, 12), text_color="#ff6b6b")
    msg.pack(anchor="w", pady=(4, 0))

    def save(*_):
        if rows and not any(show.get() for _, show, _ in rows):
            msg.configure(text="ต้องเปิดแสดงอย่างน้อย 1 อุปกรณ์ ไม่งั้นจะกลับมาเปิดหน้านี้ไม่ได้")
            return
        settings["hidden"] = [d["key"] for d, show, _ in rows if not show.get()]
        settings["names"] = {d["key"]: n.get().strip() for d, _, n in rows
                             if n.get().strip() and n.get().strip() != d["name"]}
        settings["interval"] = intervals[interval.get()]
        settings["alert"] = alerts[alert.get()]
        if startup.get() != STARTUP_LNK.exists():
            set_startup(startup.get())
        root.destroy()
        on_save()

    bar = ctk.CTkFrame(body, fg_color="transparent")
    bar.pack(fill="x", pady=(6, 0))
    ctk.CTkButton(bar, text="บันทึก", font=(TH, 13, "bold"), height=38, corner_radius=10,
                  fg_color=ACCENT, hover_color="#3b74e0", command=save).pack(side="right")
    ctk.CTkButton(bar, text="ยกเลิก", font=(TH, 13), height=38, corner_radius=10, fg_color="transparent",
                  border_width=1, border_color=LINE, hover_color=LINE, text_color=TEXT,
                  command=root.destroy).pack(side="right", padx=(0, 8))
    root.bind("<Return>", save)
    root.bind("<Escape>", lambda _: root.destroy())
    root.mainloop()


# ---------- แอป ----------

def app():
    cache = load_cache()
    first_run = "settings" not in cache
    settings = {**DEFAULTS, **cache.get("settings", {})}
    cache["settings"] = settings
    last = cache.setdefault("last", {})
    devices = discover(cache) or [{"key": "none", "kind": None, "name": "ไม่พบอุปกรณ์ที่รองรับ", "read": lambda: None}]
    save_cache(cache)
    stop, wake, lock, settings_open = threading.Event(), threading.Event(), threading.Lock(), threading.Lock()
    alerted = set()
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
                    res = None
                name = label(dev)
                if res:
                    last[dev["key"]] = [list(res), time.strftime("%d/%m %H:%M")]
                    icon.icon, icon.title = make_icon(res), tooltip(name, res)
                    low = bool(settings["alert"]) and res[0] <= settings["alert"] and not res[1]
                    if low and dev["key"] not in alerted:
                        icon.notify(f"{name} เหลือ {res[0]}% — ควรชาร์จ", "แบตใกล้หมด")
                        alerted.add(dev["key"])
                    elif not low:
                        alerted.discard(dev["key"])
                elif dev["key"] in last:
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
                settings_window(devices, settings, last, on_save=wake.set)
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
        subprocess.Popen(launch_cmd(), cwd=APP_DIR)
        quit_all()

    menu = pystray.Menu(pystray.MenuItem("ตั้งค่า...", open_settings, default=True),
                        pystray.MenuItem("รีเฟรช", lambda *_: wake.set()),
                        pystray.MenuItem("ค้นหาอุปกรณ์ใหม่", rescan),
                        pystray.Menu.SEPARATOR,
                        pystray.MenuItem("ปิด", quit_all))
    for dev in devices:
        old = last.get(dev["key"])
        start = make_icon(old[0], stale=True) if old else make_icon(None)
        icons.append(pystray.Icon("battery_" + dev["key"], start, label(dev), menu))
    for icon in icons[1:]:
        icon.run_detached()

    def loop():
        show_first = first_run
        while not stop.is_set():
            refresh()
            if show_first:
                show_first = False
                open_settings()
            wake.wait(settings["interval"])
            wake.clear()

    threading.Thread(target=loop, daemon=True).start()
    icons[0].run()


def test():
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
        res = dev["read"]()
        print(tooltip(dev["name"], res))


if __name__ == "__main__":
    test() if "--test" in sys.argv else app()
