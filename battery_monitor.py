#!/usr/bin/env python3
"""Battery Tray — แสดง % แบตเมาส์/คีย์บอร์ด/หูฟังไร้สาย ข้างนาฬิกา Windows

แหล่งข้อมูล
1. ดองเกิล 2.4G Compx/ATK (VID 3554 — VXE, ATK, Aula และแบรนด์ที่ใช้ดองเกิลเดียวกัน)
   - โปรโตคอลเมาส์ (ถอดจาก ATK HUB): ส่ง [08 04 00.. cs] 17 ไบต์, cs = 0x55 - ผลรวมไบต์ก่อนหน้า
     ตอบ r[2]=status(0=ok) r[6]=% r[7]=ชาร์จ
   - โปรโตคอลคีย์บอร์ด AULA (womier-l65-linux): ส่ง [13 4a 01 00 .. cs] 20 ไบต์,
     cs = ผลรวม 19 ไบต์แรก, ตอบ r[1]&0x7f=0x4a r[5]=%
2. อุปกรณ์ Bluetooth ที่ Windows รู้ค่าแบต (DEVPKEY_Bluetooth_Battery)

รัน:  pyw battery_monitor.py        ทดสอบ:  py battery_monitor.py --test
"""
import json
import os
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
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "hidapi", "pystray", "pillow"])
    import hid
    import pystray
    from PIL import Image, ImageDraw, ImageFont

CACHE = Path(__file__).with_name("battery_cache.json")
COMPX_VIDS = {0x3554}
VENDOR_PAGE = 0xFF02
BT_PROP = "{104EA319-6EE2-4701-BD47-8DDBF425BBE5} 2"


# ---------- โปรโตคอลดองเกิล Compx ----------

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


def hid_query(path, kind, tries=8):
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


def compx_dongles():
    """{'3554:f58e': path} ของทุกดองเกิล Compx ที่เสียบอยู่"""
    return {f"{d['vendor_id']:04x}:{d['product_id']:04x}": d["path"]
            for d in hid.enumerate()
            if d["vendor_id"] in COMPX_VIDS and d["usage_page"] == VENDOR_PAGE}


# ---------- Bluetooth ผ่าน Windows ----------

def bt_batteries():
    """{ชื่ออุปกรณ์: %} จาก Windows"""
    ps = ("Get-PnpDevice -PresentOnly -Class Bluetooth,BTHLEDevice -EA 0 | ForEach-Object {"
          f"$b=(Get-PnpDeviceProperty -InstanceId $_.InstanceId -KeyName '{BT_PROP}' -EA 0).Data;"
          "if ($b -ne $null) { \"$($_.FriendlyName)`t$b\" } }")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True,
                             text=True, encoding="utf-8", timeout=60,
                             creationflags=subprocess.CREATE_NO_WINDOW).stdout
    except (OSError, subprocess.TimeoutExpired):
        return {}
    res = {}
    for line in out.splitlines():
        name, _, pct = line.rpartition("\t")
        if name and pct.strip().isdigit():
            res[name] = int(pct)
    return res


def bt_read(name):
    v = bt_batteries().get(name)
    return (v, None) if v is not None else None


# ---------- อุปกรณ์ ----------

def load_cache():
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_cache(cache):
    CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


def discover(cache):
    """คืนรายการ {key, name, read} — ใช้ชนิดที่จำไว้ใน cache ก่อน ไม่งั้นลองทุกโปรโตคอล"""
    kinds = cache.setdefault("kinds", {})
    labels = {"mouse": "เมาส์", "keyboard": "คีย์บอร์ด", None: "อุปกรณ์"}
    devices = []
    for key, path in compx_dongles().items():
        dev = {"key": key}

        def read(path=path, key=key, dev=dev):
            kind = kinds.get(key)
            for k in [kind] if kind else PROTOCOLS:
                res = hid_query(path, k, tries=8 if kind else 3)
                if res:
                    kinds[key] = k
                    dev["name"] = f"{labels[k]} 2.4G ({key})"
                    return res
            return None

        dev["name"] = f"{labels[kinds.get(key)]} 2.4G ({key})"
        dev["read"] = read
        devices.append(dev)
    for name in bt_batteries():
        devices.append({"key": "bt:" + name, "name": name, "read": lambda n=name: bt_read(n)})
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
INTERVALS = {"30 วินาที": 30, "1 นาที": 60, "5 นาที": 300, "15 นาที": 900}
ALERTS = {"ไม่แจ้งเตือน": 0, "≤ 10%": 10, "≤ 20%": 20, "≤ 30%": 30}
DEFAULTS = {"interval": 60, "alert": 20, "hidden": [], "names": {}}


def set_startup(on):
    if not on:
        STARTUP_LNK.unlink(missing_ok=True)
        return
    script = Path(__file__).resolve()
    ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:LNK);"
          "$s.TargetPath=$env:PYW; $s.Arguments=[char]34+$env:SCRIPT+[char]34;"
          "$s.WorkingDirectory=$env:DIR; $s.Description='Battery Tray'; $s.Save()")
    env = dict(os.environ, LNK=str(STARTUP_LNK), PYW=str(Path(sys.executable).with_name("pythonw.exe")),
               SCRIPT=str(script), DIR=str(script.parent))
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], env=env,
                   creationflags=subprocess.CREATE_NO_WINDOW)


def settings_window(devices, settings, last, on_save):
    """หน้าต่างตั้งค่า (tkinter ใน thread ของตัวเอง)"""
    import tkinter as tk
    from tkinter import messagebox, ttk

    root = tk.Tk()
    root.title("Battery Tray — ตั้งค่า")
    root.resizable(False, False)
    root.attributes("-topmost", True)
    style = ttk.Style(root)
    if "vista" in style.theme_names():
        style.theme_use("vista")
    font = ("Leelawadee UI", 10)
    root.option_add("*Font", font)
    style.configure(".", font=font)
    pad = {"padx": 12, "pady": 4}

    ttk.Label(root, text="อุปกรณ์", font=("Leelawadee UI", 11, "bold")).grid(row=0, column=0, columnspan=3, sticky="w", padx=12, pady=(12, 2))
    ttk.Label(root, text="แสดง").grid(row=1, column=0, **pad)
    ttk.Label(root, text="ชื่อที่แสดง").grid(row=1, column=1, sticky="w", **pad)
    ttk.Label(root, text="แบตล่าสุด").grid(row=1, column=2, sticky="w", **pad)
    rows = []
    for i, dev in enumerate(devices, start=2):
        show = tk.BooleanVar(value=dev["key"] not in settings["hidden"])
        name = tk.StringVar(value=settings["names"].get(dev["key"], dev["name"]))
        ttk.Checkbutton(root, variable=show).grid(row=i, column=0, **pad)
        ttk.Entry(root, textvariable=name, width=30).grid(row=i, column=1, sticky="w", **pad)
        old = last.get(dev["key"])
        ttk.Label(root, text=f"{old[0][0]}%  ({old[1]})" if old else "ยังไม่ทราบ").grid(row=i, column=2, sticky="w", **pad)
        rows.append((dev, show, name))

    r = len(devices) + 2
    ttk.Separator(root).grid(row=r, column=0, columnspan=3, sticky="ew", pady=8)
    ttk.Label(root, text="ทั่วไป", font=("Leelawadee UI", 11, "bold")).grid(row=r + 1, column=0, columnspan=3, sticky="w", padx=12)
    startup = tk.BooleanVar(value=STARTUP_LNK.exists())
    ttk.Checkbutton(root, text="เปิดพร้อม Windows", variable=startup).grid(row=r + 2, column=0, columnspan=3, sticky="w", **pad)

    def combo(row, label, options, current):
        ttk.Label(root, text=label).grid(row=row, column=0, columnspan=2, sticky="w", **pad)
        var = tk.StringVar(value=next((k for k, v in options.items() if v == current), next(iter(options))))
        ttk.Combobox(root, textvariable=var, values=list(options), state="readonly", width=14).grid(row=row, column=2, sticky="w", **pad)
        return var

    interval = combo(r + 3, "อัปเดตค่าทุก", INTERVALS, settings["interval"])
    alert = combo(r + 4, "แจ้งเตือนเมื่อแบต", ALERTS, settings["alert"])

    def save(*_):
        if not any(show.get() for _, show, _ in rows):
            messagebox.showwarning("Battery Tray", "ต้องแสดงอย่างน้อย 1 อุปกรณ์\n(ไม่งั้นจะเปิดหน้าตั้งค่านี้ไม่ได้อีก)", parent=root)
            return
        settings["hidden"] = [d["key"] for d, show, _ in rows if not show.get()]
        settings["names"] = {d["key"]: n.get().strip() for d, _, n in rows
                             if n.get().strip() and n.get().strip() != d["name"]}
        settings["interval"] = INTERVALS[interval.get()]
        settings["alert"] = ALERTS[alert.get()]
        if startup.get() != STARTUP_LNK.exists():
            set_startup(startup.get())
        root.destroy()
        on_save()

    bar = ttk.Frame(root)
    bar.grid(row=r + 5, column=0, columnspan=3, sticky="e", padx=12, pady=12)
    ttk.Button(bar, text="ยกเลิก", command=root.destroy).pack(side="right", padx=(6, 0))
    ttk.Button(bar, text="บันทึก", command=save).pack(side="right")
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
    devices = discover(cache) or [{"key": "none", "name": "ไม่พบอุปกรณ์ที่รองรับ", "read": lambda: None}]
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
                res = dev["read"]()
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
        save_cache(cache)
        subprocess.Popen([sys.executable, *sys.argv])
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
    # คำตอบจริงจาก capture / อุปกรณ์
    assert mouse_frame().hex() == "0804000000000000000000000000000049"
    assert mouse_parse(bytes.fromhex("0804000000026400104c00000000000087")) == (100, False)
    assert mouse_parse(bytes.fromhex("0804010000000000000000000000000048")) is None
    assert kb_frame().hex() == "134a01000000000000000000000000000000005e"
    assert kb_parse(bytes.fromhex("134a0100025201000000000000000000000000b3")) == (82, None)
    sys.stdout.reconfigure(encoding="utf-8")
    for dev in discover(load_cache()):
        res = dev["read"]()
        print(tooltip(dev["name"], res))


if __name__ == "__main__":
    test() if "--test" in sys.argv else app()
