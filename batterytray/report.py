"""ลิงก์ "รายงานปัญหา / แจ้งอุปกรณ์" → หน้า New Issue บน GitHub ที่กรอกเวอร์ชันและรายชื่ออุปกรณ์ไว้แล้ว"""
import platform
import re
from urllib.parse import urlencode

ISSUES_NEW = "https://github.com/ChampWinai/Battery/issues/new"


def device_lines(devices, last, label):
    """หนึ่งบรรทัดต่ออุปกรณ์: ชื่อ, key (VID:PID), ชนิด, ค่าล่าสุด — ไม่มีข้อมูลส่วนตัวอื่น"""
    lines = []
    for dev in devices:
        if dev["key"] == "none":
            continue
        if dev.get("no_battery"):
            state = "ไม่ส่งค่าแบต"
        elif dev["key"] in last:
            (pct, chg), at = last[dev["key"]]
            state = f"{pct}%{' ชาร์จ' if chg else ''} (อ่านได้ล่าสุด {at})"
        else:
            state = "ยังอ่านค่าไม่ได้"
        lines.append(f"- {label(dev)} `{dev['key']}` {dev.get('kind') or '?'}: {state}")
    return lines or ["- (ไม่พบอุปกรณ์ที่รองรับ)"]


def known_usb_keys(devices):
    """VID:PID ('3554:f58e') ของอุปกรณ์ที่แอปรู้จักแล้ว — จาก key ของแต่ละแหล่ง"""
    keys = set()
    for d in devices:
        k = d["key"]
        if k.startswith("usb:"):
            keys.add(k[4:])
        elif k.startswith("logi:"):
            keys.add("046d:" + k.split(":")[1])
        elif k.startswith("hc:"):
            try:
                _, vid, pid = k.split(":")
                keys.add(f"{int(vid, 16):04x}:{int(pid, 16):04x}")
            except ValueError:
                pass
        elif re.fullmatch(r"[0-9a-f]{4}:[0-9a-f]{4}", k):
            keys.add(k)
    return keys


def hid_inventory(infos, known_keys, limit=25):
    """ช่องข้อมูลของผู้ผลิต (usage page ≥0xFF00) ที่แอปยังไม่รู้จัก — ช่วยหาดองเกิลที่ยังไม่รองรับ"""
    seen, lines = set(), []
    for d in infos:
        key = f"{d['vendor_id']:04x}:{d['product_id']:04x}"
        if d["usage_page"] < 0xFF00 or key in known_keys or (key, d["usage_page"]) in seen:
            continue
        seen.add((key, d["usage_page"]))
        name = " ".join(x for x in (d.get("manufacturer_string"), d.get("product_string")) if x).strip()
        lines.append(f"- `{key}` page 0x{d['usage_page']:04x} usage 0x{d['usage']:04x} {name}".rstrip())
    return lines[:limit] or ["- (ไม่มี)"]


def issue_url(version, lines, hid_lines=None):
    q = {"template": "device-report.yml", "version": f"v{version} · Windows {platform.release()}",
         "devices": "\n".join(lines)}
    if hid_lines:
        q["hid"] = "\n".join(hid_lines)
    return f"{ISSUES_NEW}?{urlencode(q)}"
