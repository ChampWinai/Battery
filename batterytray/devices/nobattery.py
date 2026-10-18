"""อุปกรณ์ที่ไม่ส่งค่าแบต — แสดงแค่สถานะการเชื่อมต่อ"""
import hid


# ---------- 5. อุปกรณ์ที่ไม่ส่งค่าแบต (แสดงแค่สถานะการเชื่อมต่อ) ----------

# ดองเกิลไม่ส่งค่าแบตมาที่คอม (ตรวจแล้ว: ไม่มีใน HID และโปรแกรมของผู้ผลิตก็ไม่มีฟีเจอร์แบต)
NO_BATTERY = {"040b:0897": ("หูฟัง SIGNO WP-601", "headset")}


def present_usb_keys():
    return {f"{d['vendor_id']:04x}:{d['product_id']:04x}" for d in hid.enumerate()}


def nobattery_devices(cache):
    """การ์ดสถานะการเชื่อมต่อ — แสดงเฉพาะรุ่นที่เคยเสียบในเครื่องนี้"""
    seen = cache.setdefault("seen_nobat", [])
    for key in present_usb_keys() & NO_BATTERY.keys():
        if key not in seen:
            seen.append(key)
    return [{"key": "usb:" + key, "kind": NO_BATTERY[key][1], "name": NO_BATTERY[key][0], "no_battery": True,
             "read": lambda: None, "connected": lambda k=key: k in present_usb_keys()}
            for key in seen if key in NO_BATTERY]
