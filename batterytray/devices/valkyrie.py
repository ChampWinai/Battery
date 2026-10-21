"""คีย์บอร์ด Valkyrie (VK75 / VK87 / VK99) — โปรโตคอลจากไดรเวอร์ทางการ "VK75键盘 三模 Driver-1.0.1.0"
(DeviceDriver.exe ของ FINDER/烽奇) ที่ไดรเวอร์ถามทุก 15 วินาที:

  ช่อง raw HID (FF60 32 ไบต์, report ID 0) — ไดรเวอร์เลือกจาก &mi_XX ใน path: 2.4G = MI_03, สาย USB = MI_02
  ส่ง output report 33 ไบต์: [0x00, 0x20, 0x01, 0 … 0, checksum] — checksum (ไบต์ 32) = ผลรวมไบต์ 0..31
  รับ: [0x20, 0x01, 0x00, %แบต, …] (hidapi ตัด report ID ออกแล้ว) — %แบต 0 = ยังไม่รู้ค่า
"""
import hid

RAW_PAGE = 0xFF60
RAW_PAGES = (0xFF60, 0xFF59)  # ช่อง raw 32/64 ไบต์ — ไดรเวอร์เลือกตามเลข interface (&mi_03) ไม่ใช่ usage page
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
        while dev.read(64, 0):  # ล้าง report ที่ค้าง ไม่ให้ปนกับคำตอบ
            pass
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


def _norm(s):
    return " ".join((s or "").split()).lower()


def _rank(d):
    """ลำดับเหมือนไดรเวอร์: 2.4G = MI_03, สาย = MI_02, แล้วค่อยช่อง FF60 / FF59 อื่น"""
    i = d.get("interface_number", -1)
    return ({3: 0, 2: 1}.get(i, 2), RAW_PAGES.index(d["usage_page"]))


def _reader(paths):
    def read():
        for p in list(paths):
            got = query(p)
            if got:
                paths.remove(p)
                paths.insert(0, p)  # จำช่องที่ตอบ ถามช่องนี้ก่อนรอบหน้า
                return got
        return None
    return read


def valkyrie_devices():
    found = {}
    for d in hid.enumerate():
        names = PRODUCTS.get((d["vendor_id"], d["product_id"]))
        product = (d.get("product_string") or "").strip()
        if not names or d["usage_page"] not in RAW_PAGES or _norm(product) not in {_norm(n) for n in names}:
            continue
        key = f"{d['vendor_id']:04x}:{d['product_id']:04x}"
        found.setdefault(key, (product, []))[1].append(d)
    return [{"key": k, "kind": "keyboard", "name": label(product),
             "read": _reader([d["path"] for d in sorted(ds, key=_rank)])}
            for k, (product, ds) in found.items()]
