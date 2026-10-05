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

REFRESH_S = 60
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


# ---------- แอป ----------

def app():
    cache = load_cache()
    last = cache.setdefault("last", {})
    devices = discover(cache) or [{"key": "none", "name": "ไม่พบอุปกรณ์ที่รองรับ", "read": lambda: None}]
    save_cache(cache)
    stop = threading.Event()
    icons = []

    def refresh(*_):
        for dev, icon in zip(devices, icons):
            res = dev["read"]()
            if res:
                last[dev["key"]] = [list(res), time.strftime("%d/%m %H:%M")]
                icon.icon, icon.title = make_icon(res), tooltip(dev["name"], res)
            elif dev["key"] in last:
                old, at = last[dev["key"]]
                icon.icon = make_icon(old, stale=True)
                icon.title = f"{dev['name']}: {old[0]}% (ค่าล่าสุด {at}, ตอนนี้หลับอยู่)"
            else:
                icon.icon, icon.title = make_icon(None), tooltip(dev["name"], None)
        save_cache(cache)

    def quit_all(*_):
        stop.set()
        for icon in icons:
            icon.stop()

    def rescan(*_):
        # ponytail: เริ่มโปรเซสใหม่แทนการเพิ่ม/ลบไอคอนสด ๆ
        cache.pop("kinds", None)
        save_cache(cache)
        subprocess.Popen([sys.executable, *sys.argv])
        quit_all()

    menu = pystray.Menu(pystray.MenuItem("รีเฟรช", refresh, default=True),
                        pystray.MenuItem("ค้นหาอุปกรณ์ใหม่", rescan),
                        pystray.MenuItem("ปิด", quit_all))
    for dev in devices:
        old = last.get(dev["key"])
        start = make_icon(old[0], stale=True) if old else make_icon(None)
        icons.append(pystray.Icon("battery_" + dev["key"], start, dev["name"], menu))
    for icon in icons[1:]:
        icon.run_detached()

    def loop():
        while not stop.is_set():
            refresh()
            stop.wait(REFRESH_S)

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
