"""ดองเกิล 2.4G ระบบเดียวกับ VK HUB (Valkyrie) — เช่น VK75 Wireless Receiver (05AC:024F)

โปรโตคอล (จาก VK HUB web driver, ___dongleCheck24GStatusByF7):
  ช่องคีย์บอร์ดหลัก (usage page 1 / usage 6) feature report ID 0 ยาว 64 ไบต์
  ส่ง [0x00, 0xF7, 0...] → อ่าน feature report 0 กลับ (ตัดไบต์ report ID) = n
  n[0]==1 อ่านได้, n[1] = % คีย์บอร์ด, n[2] = % เมาส์, n[3]==0 คีย์บอร์ดออนไลน์, n[6] = 1 คีย์บอร์ด / 2 เมาส์ / 3 ทั้งคู่
"""
import time

import hid

# VID:PID ที่ VK HUB จัดเป็นคีย์บอร์ด 2.4G — ส่งคำสั่งเฉพาะเมื่อมี feature report 0 ขนาด 64 ไบต์ (กันคีย์บอร์ด Apple แท้)
VKHUB_IDS = {(0x05AC, 0x024F)}
FEATURE_LEN = 64
STATUS_CMD = 0xF7


def feature_sizes(desc):
    """{report_id: จำนวนไบต์} ของ Feature report จาก HID report descriptor (short items เท่านั้น)"""
    sizes, rid, size, count, i = {}, 0, 0, 0, 0
    while i < len(desc):
        b = desc[i]
        if b == 0xFE:  # long item
            i += 3 + (desc[i + 1] if i + 1 < len(desc) else 0)
            continue
        n = (0, 1, 2, 4)[b & 3]
        val = int.from_bytes(bytes(desc[i + 1:i + 1 + n]), "little") if n else 0
        tag = b & 0xFC
        if tag == 0x84:
            rid = val
        elif tag == 0x74:
            size = val
        elif tag == 0x94:
            count = val
        elif tag == 0xB0:  # Feature
            sizes[rid] = sizes.get(rid, 0) + size * count // 8
        i += 1 + n
    return sizes


def status_frame(length=FEATURE_LEN):
    return bytes([0x00, STATUS_CMD] + [0] * (length - 1))


def parse_status(n):
    """(pct, None) ของคีย์บอร์ด หรือ None ถ้ายังอ่านไม่ได้ / คีย์บอร์ดไม่ออนไลน์"""
    if len(n) < 7 or n[0] != 1 or n[6] not in (1, 3) or n[3] != 0 or not 0 <= n[1] <= 100:
        return None
    return n[1], None


def query(path, length):
    dev = hid.device()
    try:
        dev.open_path(path)
    except OSError:
        return None
    try:
        if dev.send_feature_report(status_frame(length)) < 0:
            return None
        time.sleep(0.02)
        r = dev.get_feature_report(0, length + 1)
        return parse_status(bytes(r[1:])) if r else None
    except OSError:
        return None
    finally:
        dev.close()


def vkhub_devices():
    devices = []
    for d in hid.enumerate():
        if (d["vendor_id"], d["product_id"]) not in VKHUB_IDS or (d["usage_page"], d["usage"]) != (1, 6):
            continue
        dev = hid.device()
        try:
            dev.open_path(d["path"])
            sizes = feature_sizes(bytes(dev.get_report_descriptor()))
        except Exception:
            continue
        finally:
            dev.close()
        if sizes.get(0, 0) < FEATURE_LEN:
            continue  # ไม่ใช่ดองเกิลระบบ VK HUB (เช่น คีย์บอร์ด Apple แท้)
        key = f"{d['vendor_id']:04x}:{d['product_id']:04x}"
        name = (d.get("product_string") or "").replace("Wireless Receiver", "").strip() or f"คีย์บอร์ด 2.4G ({key})"
        devices.append({"key": key, "kind": "keyboard", "name": name,
                        "read": lambda p=d["path"], n=sizes[0]: query(p, n)})
    return devices
