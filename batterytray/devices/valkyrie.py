"""คีย์บอร์ด Valkyrie (VK75 / VK87 / VK99) — โปรโตคอลจากไดรเวอร์ทางการ "VK75键盘 三模 Driver-1.0.1.0"
(DeviceDriver.exe ของ FINDER/烽奇) ที่ไดรเวอร์ถามทุก 15 วินาที:

  ช่อง raw HID usage page 0xFF60 (32 ไบต์, report ID 0) — 2.4G ใช้ interface MI_03, สาย USB ใช้ MI_02
  ส่ง output report 33 ไบต์: [0x00, 0x20, 0x01, 0 … 0, checksum] — checksum (ไบต์ 32) = ผลรวมไบต์ 0..31
  รับ: [0x20, 0x01, 0x00, %แบต, …] (hidapi ตัด report ID ออกแล้ว) — %แบต 0 = ยังไม่รู้ค่า
"""
import hid

RAW_PAGE = 0xFF60
# VID:PID → ชื่อสินค้าตาม config.xml ของไดรเวอร์ Valkyrie — ส่งคำสั่งเฉพาะเมื่อชื่อตรง (05AC:024F ใช้ร่วมกับยี่ห้ออื่น)
PRODUCTS = {
    (0x05AC, 0x024F): {"VK 75 Wireless Receiver", "Valkyrie 75", "VK87", "Valkyrie-99", "2.4G Wireless Receiver",
                       "Valkyrie-99pro", "VK99Pro Wireless Receiver"},
    (0x0C45, 0xFEFE): {"2.4G Dongle"},
}


def battery_frame():
    pkt = [0x00, 0x20, 0x01] + [0] * 30
    pkt[32] = sum(pkt[:32]) & 0xFF
    return bytes(pkt)


def parse_battery(r):
    """(pct, None) หรือ None ถ้าไม่ใช่คำตอบของคำสั่งแบต / ยังไม่รู้ค่า"""
    if len(r) < 4 or list(r[:3]) != [0x20, 0x01, 0x00] or not r[3]:
        return None
    return min(r[3], 100), None


def query(path, tries=20):
    dev = hid.device()
    try:
        dev.open_path(path)
    except OSError:
        return None
    try:
        if dev.write(battery_frame()) < 0:
            return None
        for _ in range(tries):  # ไดรเวอร์อ่านซ้ำได้ 20 ครั้งจนกว่าคำตอบจะตรงคำสั่ง
            r = dev.read(64, 50)
            got = parse_battery(bytes(r)) if r else None
            if got:
                return got
    except OSError:
        pass
    finally:
        dev.close()
    return None


def label(product):
    name = product.replace("Wireless Receiver", "").replace("2.4G Dongle", "").strip(" -")
    return name if name and not name.startswith("2.4G") else "คีย์บอร์ด Valkyrie"


def valkyrie_devices():
    devices, seen = [], set()
    for d in hid.enumerate():
        names = PRODUCTS.get((d["vendor_id"], d["product_id"]))
        product = (d.get("product_string") or "").strip()
        if not names or d["usage_page"] != RAW_PAGE or product not in names:
            continue
        key = f"{d['vendor_id']:04x}:{d['product_id']:04x}"
        if key in seen:
            continue
        seen.add(key)
        devices.append({"key": key, "kind": "keyboard", "name": label(product),
                        "read": lambda p=d["path"]: query(p)})
    return devices
