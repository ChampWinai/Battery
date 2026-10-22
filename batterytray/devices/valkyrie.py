"""คีย์บอร์ด Valkyrie (VK75 / VK87 / VK99) — โปรโตคอลจากไดรเวอร์ทางการ "VK75键盘 三模 Driver-1.0.1.0"
(DeviceDriver.exe ของ FINDER/烽奇) ที่ไดรเวอร์ถามทุก 15 วินาที:

  ช่อง raw HID (FF60 32 ไบต์, report ID 0) — ไดรเวอร์เลือกจาก &mi_XX ใน path: 2.4G = MI_03, สาย USB = MI_02
  ส่ง output report 33 ไบต์: [0x00, 0x20, 0x01, 0 … 0, checksum] — checksum (ไบต์ 32) = ผลรวมไบต์ 0..31
  รับ: [0x20, 0x01, 0x00, %แบต, …] (hidapi ตัด report ID ออกแล้ว) — %แบต 0 = ยังไม่รู้ค่า
  ไดรเวอร์: เขียนซ้ำ 1 ครั้งถ้าเขียนไม่ผ่าน, อ่านซ้ำ 20 ครั้งจนคำตอบตรง — ไม่มีคำสั่งเปิดการเชื่อมต่อก่อนถามแบต
"""
import hid

RAW_PAGE = 0xFF60
RAW_PAGES = (0xFF60, 0xFF59)  # ช่อง raw 32/64 ไบต์ — ไดรเวอร์เลือกตามเลข interface (&mi_03) ไม่ใช่ usage page
# VID:PID ดองเกิลตาม config.xml ของไดรเวอร์ Valkyrie — 05AC:024F ใช้ร่วมกับคีย์บอร์ด Apple แต่ของ Apple ไม่มีช่อง
# raw HID 0xFF60 (แบบ QMK) จึงใช้ช่องนี้เป็นตัวกันพลาด ไม่ใช้ชื่อสินค้า (Windows คืนชื่อของแต่ละช่องไม่ตรงกัน)
PRODUCTS = {(0x05AC, 0x024F), (0x0C45, 0xFEFE)}


def battery_frame():
    pkt = [0x00, 0x20, 0x01] + [0] * 30
    pkt[32] = sum(pkt[:32]) & 0xFF
    return bytes(pkt)


def parse_battery(r):
    """(pct, None) หรือ None ถ้าไม่ใช่คำตอบของคำสั่งแบต / ยังไม่รู้ค่า — รับทั้งแบบที่มี report ID 0 นำหน้า"""
    r = bytes(r)
    if r[:2] == b"\x00\x20":
        r = r[1:]
    if len(r) < 4 or list(r[:3]) != [0x20, 0x01, 0x00] or not r[3]:
        return None
    return min(r[3], 100), None


TRACE = {}  # path → บันทึกการคุยรอบล่าสุด (แนบในผลสแกน เพื่อดูว่าติดขั้นไหน)


def _open(path):
    dev = hid.device()
    dev.open_path(path)
    dev.set_nonblocking(True)
    while dev.read(64):  # ล้าง report ที่ค้าง ไม่ให้ปนกับคำตอบ
        pass
    return dev


def query(path, listen=(), rounds=2, wait=1.0):
    """เขียนคำสั่งแบตทาง path แล้วฟังคำตอบจาก path และทุกช่องใน listen (เผื่อดองเกิลตอบทางช่องอื่น)
    ส่งซ้ำได้ rounds รอบ (เผื่อคีย์บอร์ดกำลังตื่น) — แต่ละรอบรอ wait วินาที"""
    import time
    log = TRACE[path] = []
    devs = {}
    try:
        for p in [path] + [p for p in listen if p != path]:
            try:
                devs[p] = _open(p)
            except OSError as e:
                if p == path:
                    log.append(f"open: {e}")
                    return None
        tag = {p: "" if p == path else f"(ช่อง {i}) " for i, p in enumerate(devs)}
        for _ in range(rounds):
            n = devs[path].write(battery_frame())
            if n < 0:  # ไดรเวอร์เขียนซ้ำหนึ่งครั้งเมื่อเขียนไม่ผ่าน
                time.sleep(0.01)
                n = devs[path].write(battery_frame())
            log.append(f"write {n}")
            if n < 0:
                return None
            end = time.time() + wait
            while time.time() < end:
                for p, dev in devs.items():
                    r = bytes(dev.read(64))
                    if not r:
                        continue
                    if len(log) < 8:
                        log.append(tag[p] + r[:8].hex())
                    got = parse_battery(r)
                    if got:
                        return got
                time.sleep(0.01)
        log.append("no reply" if all(x.startswith("write") for x in log) else "no match")
    except OSError as e:
        log.append(f"error: {e}")
    finally:
        for dev in devs.values():
            dev.close()
    return None


def label(product):
    name = product.replace("Wireless Receiver", "").replace("2.4G Dongle", "").strip(" -")
    return name if name and not name.startswith("2.4G") else "คีย์บอร์ด Valkyrie"


def _rank(d):
    """ลำดับเหมือนไดรเวอร์: 2.4G = MI_03, สาย = MI_02, แล้วค่อยช่อง FF60 / FF59 อื่น"""
    i = d.get("interface_number", -1)
    return ({3: 0, 2: 1}.get(i, 2), RAW_PAGES.index(d["usage_page"]))


def _reader(paths):
    def read():
        for p in list(paths):
            got = query(p, paths)
            if got:
                paths.remove(p)
                paths.insert(0, p)  # จำช่องที่ตอบ ถามช่องนี้ก่อนรอบหน้า
                return got
        return None
    return read


def valkyrie_devices():
    found, names = {}, {}
    for d in hid.enumerate():
        if (d["vendor_id"], d["product_id"]) not in PRODUCTS:
            continue
        key = f"{d['vendor_id']:04x}:{d['product_id']:04x}"
        names[key] = names.get(key) or (d.get("product_string") or "").strip()
        if d["usage_page"] in RAW_PAGES:
            found.setdefault(key, []).append(d)
    out = []
    for k, ds in found.items():
        if not any(d["usage_page"] == RAW_PAGE for d in ds):
            continue  # ไม่มีช่อง FF60 = ไม่ใช่ดองเกิล Valkyrie
        ds, product = sorted(ds, key=_rank), names[k]
        out.append({"key": k, "kind": "keyboard", "name": label(product),
                    "read": _reader([d["path"] for d in ds]),
                    "debug": lambda ds=ds: [f"mi{d.get('interface_number')} 0x{d['usage_page']:04x}: "
                                            + " / ".join(TRACE.get(d["path"], ["(ยังไม่ได้ถาม)"])) for d in ds]})
    return out
