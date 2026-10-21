"""สแกนอุปกรณ์ HID ทั้งหมดในเครื่อง → สถานะต่ออุปกรณ์ + ข้อความรายงานสำหรับเพิ่มรองรับดองเกิลใหม่

ส่งคำสั่งเฉพาะแหล่งที่รู้วิธีอ่านแบตแล้ว (ผ่าน read() ของแต่ละอุปกรณ์) — อุปกรณ์อื่นแค่อ่าน descriptor
"""
from batterytray.report import usb_key

OK, INFO, FOUND, UNSUPPORTED = "ok", "info", "found", "unsupported"


def group_hid(infos):
    """{'vid:pid': {name, pages: [(page, usage)], paths: {page: path}}} — รวมทุก collection ของอุปกรณ์เดียวกัน"""
    out = {}
    for d in infos:
        key = f"{d['vendor_id']:04x}:{d['product_id']:04x}"
        g = out.setdefault(key, {"name": "", "pages": [], "paths": {}})
        name = " ".join(x for x in (d.get("manufacturer_string"), d.get("product_string")) if x).strip()
        g["name"] = g["name"] or name
        if (d["usage_page"], d["usage"]) not in g["pages"]:
            g["pages"].append((d["usage_page"], d["usage"]))
        g["paths"].setdefault(d["usage_page"], d["path"])
    return out


def build_entries(groups, devices, results, descriptors=None, samples=None):
    """รวมผลสแกน: อุปกรณ์ที่แอปรู้จัก (อ่านได้/ยังไม่ได้) + อุปกรณ์ที่มีช่องผู้ผลิตแต่ยังไม่รองรับ
    results = {dev key: (pct, charging) หรือ None}, descriptors/samples = {(vid:pid, page): hex / [hex]}"""
    descriptors, samples = descriptors or {}, samples or {}
    entries, claimed = [], set()
    for dev in devices:
        if dev["key"] == "none":
            continue
        k = usb_key(dev)
        g = groups.get(k, {}) if k else {}
        claimed.add(k)
        res = results.get(dev["key"])
        if dev.get("no_battery"):
            status, detail = INFO, "เชื่อมต่ออยู่ · รุ่นนี้ไม่ส่งค่าแบต"
        elif res:
            status, detail = OK, f"{res[0]}%" + (" กำลังชาร์จ" if res[1] else "")
        else:
            status, detail = FOUND, "เจอแต่ยังอ่านแบตไม่ได้ (ลองขยับ/กดปุ่มอุปกรณ์แล้วสแกนใหม่)"
        entries.append({"key": k or dev["key"], "name": g.get("name") or dev["name"], "app_name": dev["name"],
                        "status": status, "detail": detail, "pages": g.get("pages", []), "readable": bool(res),
                        "no_battery": bool(dev.get("no_battery"))})
    for k, g in groups.items():
        if k in claimed or not any(p >= 0xFF00 for p, _ in g["pages"]):
            continue  # อุปกรณ์ HID มาตรฐานทั่วไป (ไม่มีช่องผู้ผลิต) — ไม่มีทางอ่านแบตได้จากที่นี่
        entries.append({"key": k, "name": g["name"] or "(ไม่มีชื่อ)", "app_name": None, "status": UNSUPPORTED,
                        "detail": "ยังไม่รองรับ — กดส่งผลสแกนเพื่อช่วยเพิ่ม", "pages": g["pages"], "readable": False,
                        "no_battery": False})
    for e in entries:
        e["descriptors"] = {pg: descriptors[(e["key"], pg)] for pg, _ in e["pages"] if (e["key"], pg) in descriptors}
        e["samples"] = {pg: samples[(e["key"], pg)] for pg, _ in e["pages"] if samples.get((e["key"], pg))}
    order = {OK: 0, INFO: 1, FOUND: 2, UNSUPPORTED: 3}
    return sorted(entries, key=lambda e: (order[e["status"]], e["name"]))


def scan_lines(entries, max_desc=96, max_samples=3, sample_bytes=32):
    """ข้อความรายงาน: ทุกอุปกรณ์ + รายละเอียดช่อง/descriptor ของตัวที่อ่านไม่ได้"""
    icon = {OK: "✅", INFO: "ℹ️", FOUND: "⚠️", UNSUPPORTED: "❔"}
    lines = []
    for e in entries:
        lines.append(f"{icon[e['status']]} `{e['key']}` {e['name']} — {e['detail']}")
        if e["status"] != OK and not e["no_battery"]:
            for page, usage in e["pages"]:
                if page < 0xFF00:
                    continue
                desc = e["descriptors"].get(page, "")
                cut = desc[:max_desc * 2] + ("…" if len(desc) > max_desc * 2 else "")
                lines.append(f"    page 0x{page:04x} usage 0x{usage:04x}" + (f" desc {cut}" if desc else ""))
                for hx in e.get("samples", {}).get(page, [])[:max_samples]:
                    lines.append(f"      ↳ ส่งออกมาเอง: {hx[:sample_bytes * 2]}" + ("…" if len(hx) > sample_bytes * 2 else ""))
    return lines or ["(ไม่พบอุปกรณ์)"]


def read_descriptors(groups, keys):
    """อ่าน report descriptor ของช่องผู้ผลิต (อ่านอย่างเดียว ไม่ส่งคำสั่ง) ของอุปกรณ์ใน keys"""
    import hid
    out = {}
    for k in keys:
        for page, path in groups.get(k, {}).get("paths", {}).items():
            if page < 0xFF00:
                continue
            dev = hid.device()
            try:
                dev.open_path(path)
                out[(k, page)] = bytes(dev.get_report_descriptor()).hex()
            except Exception:
                pass
            finally:
                try:
                    dev.close()
                except Exception:
                    pass
    return out


def listen_reports(groups, keys, seconds=10, per_page=6):
    """ฟัง input report ที่อุปกรณ์ส่งออกมาเอง (อ่านอย่างเดียว ไม่ส่งคำสั่ง) บนช่องผู้ผลิตของ keys
    คืน {(vid:pid, page): [hex ไม่ซ้ำ ตามลำดับที่เจอ]}"""
    import time

    import hid
    handles = []
    for k in keys:
        for page, path in groups.get(k, {}).get("paths", {}).items():
            if page < 0xFF00:
                continue
            dev = hid.device()
            try:
                dev.open_path(path)
                dev.set_nonblocking(True)
                handles.append(((k, page), dev))
            except Exception:
                pass
    out = {}
    try:
        end = time.time() + seconds
        while time.time() < end and handles:
            for kp, dev in handles:
                try:
                    r = dev.read(64)
                except Exception:
                    continue
                if r:
                    hx = bytes(r).hex()
                    got = out.setdefault(kp, [])
                    if hx not in got and len(got) < per_page:
                        got.append(hx)
            time.sleep(0.01)
    finally:
        for _, dev in handles:
            try:
                dev.close()
            except Exception:
                pass
    return out
