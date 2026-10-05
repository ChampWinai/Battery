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
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "hidapi", "pystray", "pillow", "customtkinter"])
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


def settings_window(devices, settings, last, kinds, on_save):
    """หน้าต่างตั้งค่า (customtkinter ใน thread ของตัวเอง)"""
    import customtkinter as ctk

    BG, CARD, LINE = "#0e1014", "#171a21", "#232733"
    TEXT, MUTED, ACCENT = "#eef0f4", "#8a90a0", "#4f8cff"
    TH = "Leelawadee UI"
    GLYPH = {"mouse": "", "keyboard": "", None: ""}  # Segoe MDL2 Assets

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
    for dev in devices:
        old = last.get(dev["key"])
        pct = old[0][0] if old else None
        color = "#%02x%02x%02x" % level_color(pct) if pct is not None else MUTED

        card = ctk.CTkFrame(body, fg_color=CARD, corner_radius=16, border_width=1, border_color=LINE)
        card.pack(fill="x", pady=5)
        card.grid_columnconfigure(1, weight=1)

        badge = ctk.CTkFrame(card, width=46, height=46, corner_radius=12, fg_color=LINE)
        badge.grid(row=0, column=0, rowspan=2, padx=(14, 12), pady=14)
        badge.grid_propagate(False)
        kind = kinds.get(dev["key"]) if not dev["key"].startswith("bt:") else None
        ctk.CTkLabel(badge, text=GLYPH.get(kind, GLYPH[None]), font=("Segoe MDL2 Assets", 20),
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

    row_label(0, "เปิดพร้อม Windows", "เริ่มทำงานเองทุกครั้งที่เปิดเครื่อง")
    startup = ctk.BooleanVar(value=STARTUP_LNK.exists())
    ctk.CTkSwitch(gen, text="", variable=startup, width=46, progress_color=ACCENT).grid(row=0, column=1, padx=16, sticky="e")
    row_label(1, "อัปเดตค่าทุก", "ถี่ขึ้น = เห็นค่าใหม่เร็วขึ้น")
    interval = segmented(1, {"30 วิ": 30, "1 นาที": 60, "5 นาที": 300, "15 นาที": 900}, settings["interval"])
    row_label(2, "แจ้งเตือนแบตต่ำ", "เด้งแจ้งเตือนครั้งเดียวเมื่อแบตต่ำกว่าค่านี้")
    alert = segmented(2, {"ปิด": 0, "10%": 10, "20%": 20, "30%": 30}, settings["alert"])

    msg = ctk.CTkLabel(body, text="", font=(TH, 12), text_color="#ff6b6b")
    msg.pack(anchor="w", pady=(8, 0))

    def save(*_):
        if not any(show.get() for _, show, _ in rows):
            msg.configure(text="ต้องเปิดแสดงอย่างน้อย 1 อุปกรณ์ ไม่งั้นจะกลับมาเปิดหน้านี้ไม่ได้")
            return
        settings["hidden"] = [d["key"] for d, show, _ in rows if not show.get()]
        settings["names"] = {d["key"]: n.get().strip() for d, _, n in rows
                             if n.get().strip() and n.get().strip() != d["name"]}
        settings["interval"] = {"30 วิ": 30, "1 นาที": 60, "5 นาที": 300, "15 นาที": 900}[interval.get()]
        settings["alert"] = {"ปิด": 0, "10%": 10, "20%": 20, "30%": 30}[alert.get()]
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
                settings_window(devices, settings, last, cache["kinds"], on_save=wake.set)
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
