"""Logitech HID++ 2.0 — feature 0x1004 / 0x1000 / 0x1001"""
import hid
import time


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
