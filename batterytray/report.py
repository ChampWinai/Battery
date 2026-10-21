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


def usb_key(dev):
    """VID:PID ('3554:f58e') ของอุปกรณ์จาก key ของแต่ละแหล่ง หรือ None (เช่น Bluetooth)"""
    k = dev["key"]
    if k.startswith("usb:"):
        return k[4:]
    if k.startswith("logi:"):
        return "046d:" + k.split(":")[1]
    if k.startswith("hc:"):
        try:
            _, vid, pid = k.split(":")
            return f"{int(vid, 16):04x}:{int(pid, 16):04x}"
        except ValueError:
            return None
    return k if re.fullmatch(r"[0-9a-f]{4}:[0-9a-f]{4}", k) else None


def issue_url(version, lines, hid_lines=None):
    q = {"template": "device-report.yml", "version": f"v{version} · Windows {platform.release()}",
         "devices": "\n".join(lines)}
    if hid_lines:
        q["hid"] = "\n".join(hid_lines)
    return f"{ISSUES_NEW}?{urlencode(q)}"
