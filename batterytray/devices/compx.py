"""ดองเกิล 2.4G Compx/ATK (VID 3554, 373B) — เมาส์ (ATK HUB) และคีย์บอร์ด (AULA)"""
import hid
import time


# ---------- 1. ดองเกิล Compx ----------

# 373B:1085 = ดองเกิล 1K ของ VXE R1 SE+ บางล็อต — โปรโตคอลเดียวกับ 3554 (HeyOkay/HaloBattery#36)
COMPX_VIDS = {0x3554, 0x373B}
VENDOR_PAGE = 0xFF02


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


def pick_paths(infos):
    """{'vid:pid': path} หนึ่งช่องต่อดองเกิล — ใช้หน้า 0xFF02 ก่อน ถ้าไม่มีใช้หน้าของผู้ผลิตที่ต่ำสุด (≥0xFF00)"""
    best = {}
    for d in infos:
        if d["vendor_id"] not in COMPX_VIDS or d["usage_page"] < 0xFF00:
            continue
        key = f"{d['vendor_id']:04x}:{d['product_id']:04x}"
        rank = (d["usage_page"] != VENDOR_PAGE, d["usage_page"])
        if key not in best or rank < best[key][0]:
            best[key] = (rank, d["path"])
    return {k: path for k, (_, path) in best.items()}


def compx_devices(kinds):
    labels = {"mouse": "เมาส์", "keyboard": "คีย์บอร์ด", None: "อุปกรณ์"}
    paths = pick_paths(hid.enumerate())
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
