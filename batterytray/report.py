"""ลิงก์ "รายงานปัญหา / แจ้งอุปกรณ์" → หน้า New Issue บน GitHub ที่กรอกเวอร์ชันและรายชื่ออุปกรณ์ไว้แล้ว"""
import platform
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


def issue_url(version, lines):
    q = {"template": "device-report.yml", "version": f"v{version} · Windows {platform.release()}",
         "devices": "\n".join(lines)}
    return f"{ISSUES_NEW}?{urlencode(q)}"
