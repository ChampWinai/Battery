"""ชุดทดสอบ: py battery_monitor.py --test"""
from pathlib import Path
import json
import os
import subprocess
import sys
from batterytray.config import APP_DIR, EXE_NAME, load_cache
from batterytray.devices import discover
from batterytray.devices.compx import kb_frame, kb_parse, mouse_frame, mouse_parse, candidate_paths
from batterytray.devices.headsetcontrol import headsetcontrol_parse
from batterytray.devices.logitech import logi_battery, volt_to_pct
from batterytray.devices import nobattery
from batterytray.devices.nobattery import nobattery_devices
from batterytray.history import estimate_remaining_h, fmt_remaining, fmt_span, history_points, record_history
from batterytray.icons import tooltip
from batterytray.report import device_lines, issue_url, usb_key
from batterytray.scan import build_entries, group_hid, scan_lines
from batterytray.system import acquire_single_instance, install_copy, needs_install, same_dir
from batterytray.updater import download_update, is_newer, swap_exe


def test():
    assert is_newer("v1.2.0", "1.1.0") and is_newer("v1.10.0", "1.9.0")
    assert not is_newer("v1.1.0", "1.1.0") and not is_newer("v1.0.0", "1.1.0") and not is_newer("beta", "1.1.0")

    # ประมาณเวลาที่เหลือ: ข้อมูลน้อย/ช่วงชาร์จ → None
    H = 3600
    hist = []
    for i, p in enumerate([80, 78, 76, 74, 72, 70]):  # ลด 2% ทุก 24 นาที = 5%/ชม. รวม 2 ชม.
        record_history(hist, 1000 + i * 1440, p, False)
    assert round(estimate_remaining_h(hist, 1000 + 5 * 1440), 1) == 14.0  # 70% / 5%/ชม.
    assert round(estimate_remaining_h(hist, 1000 + 5 * 1440 + 4 * H), 1) == 10.0  # ผ่านไปอีก 4 ชม.
    assert estimate_remaining_h(hist[:3], 1000 + 2 * 1440) is None       # ยังไม่ถึง 2 ชม.
    hist2 = [[0, 90, False], [2 * H, 80, False], [3 * H, 60, True], [3 * H + 60, 85, False]]
    assert estimate_remaining_h(hist2, 3 * H + 60) is None               # เพิ่งชาร์จ เริ่มนับใหม่
    hist3 = [[0, 50, False], [H, 40, False], [2 * H, 70, False], [5 * H, 64, False]]
    assert round(estimate_remaining_h(hist3, 5 * H)) == 32               # ใช้เฉพาะช่วงหลังแบตเพิ่ม: 2%/ชม.
    pts, span = history_points([[-1, 80, False], [0, 100, False], [3.5 * 86400, 50, True], [7 * 86400, 0, False]],
                               7 * 86400, 108, 108)
    assert span == 7 * 86400 and pts == [(4, 4, False), (54, 54, True), (104, 104, False)]  # เก่ากว่า 7 วันถูกตัด
    pts, span = history_points([[10 * H, 80, False], [12 * H, 70, False]], 13 * H, 108, 108)
    assert span == 3 * H and pts[0][0] == 4 and fmt_span(span) == "3 ชม.ก่อน"  # แกนเริ่มที่จุดแรก
    assert history_points([], 0, 100, 100) == ([], 3600) and fmt_span(2 * 86400) == "2 วันก่อน"
    assert fmt_remaining(0.5) == "ไม่ถึง 1 ชม." and fmt_remaining(7.4) == "~7 ชม." and fmt_remaining(72) == "~3 วัน"
    old_hist = []
    record_history(old_hist, 0, 50, False)
    record_history(old_hist, 8 * 86400, 49, False)
    assert len(old_hist) == 1                                            # เก่ากว่า 7 วันถูกลบ
    rh = []
    record_history(rh, 0, 50, False)
    record_history(rh, 60, 50, False)
    assert len(rh) == 1                                                  # ค่าไม่เปลี่ยน ไม่เก็บซ้ำทุกนาที

    # ติดตั้งไว้ที่ถาวร: คัดลอกใหม่ / แทนตัวเดิม; ไม่ติดตั้งตอนรันจากซอร์ส
    import tempfile
    assert not needs_install()
    assert same_dir("C:\\Users\\X\\AppData\\Local\\BatteryTray", "c:\\users\\x\\appdata\\local\\batterytray\\")
    assert not same_dir("C:\\Users\\X\\Downloads", "C:\\Users\\X\\AppData\\Local\\BatteryTray")
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        src = d / "Downloads" / EXE_NAME
        src.parent.mkdir()
        src.write_bytes(b"MZ v2")
        dest = d / "Install" / EXE_NAME
        install_copy(src, dest)
        assert dest.read_bytes() == b"MZ v2"
        src.write_bytes(b"MZ v3")
        install_copy(src, dest)
        assert dest.read_bytes() == b"MZ v3"

    # กันเปิดซ้ำ: ตัวแรกได้ mutex, โปรเซสอื่นที่ขอชื่อเดียวกันต้องถูกปฏิเสธ
    name = f"Local\\BatteryTray.Test.{os.getpid()}"
    assert acquire_single_instance(0, name)
    probe = ("import sys; sys.path.insert(0, %r); from batterytray.system import acquire_single_instance; "
             "print(acquire_single_instance(0, %r))" % (str(APP_DIR), name))
    out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, timeout=60).stdout.strip()
    assert out.endswith("False"), out

    # รายงานปัญหา: บรรทัดอุปกรณ์ + ลิงก์ issue form ที่กรอกค่าไว้
    from urllib.parse import parse_qs, urlparse
    devs = [{"key": "3554:f58e", "kind": "mouse", "name": "เมาส์"}, {"key": "usb:040b:0897", "kind": "headset",
            "name": "หูฟัง", "no_battery": True}, {"key": "logi:c547:1", "kind": None, "name": "Logi"}]
    lines = device_lines(devs, {"3554:f58e": [[65, True], "18/10 14:00"]}, lambda d: d["name"])
    assert lines == ["- เมาส์ `3554:f58e` mouse: 65% ชาร์จ (อ่านได้ล่าสุด 18/10 14:00)",
                     "- หูฟัง `usb:040b:0897` headset: ไม่ส่งค่าแบต", "- Logi `logi:c547:1` ?: ยังอ่านค่าไม่ได้"]
    assert device_lines([], {}, str) == ["- (ไม่พบอุปกรณ์ที่รองรับ)"]
    q = parse_qs(urlparse(issue_url("9.9.9", lines)).query)
    assert q["template"] == ["device-report.yml"] and q["version"][0].startswith("v9.9.9")
    assert q["devices"] == ["\n".join(lines)]

    # ดองเกิล Compx: รับทั้ง VID 3554 และ 373B, เลือกหน้า 0xFF02 ก่อน ไม่มีค่อยใช้หน้าผู้ผลิตที่ต่ำสุด
    hid_list = [
        {"vendor_id": 0x3554, "product_id": 0xF58E, "usage_page": 0xFF05, "usage": 0, "path": b"a5"},
        {"vendor_id": 0x3554, "product_id": 0xF58E, "usage_page": 0xFF02, "usage": 2, "path": b"a2"},
        {"vendor_id": 0x373B, "product_id": 0x1085, "usage_page": 0xFF04, "usage": 2, "path": b"b4"},
        {"vendor_id": 0x373B, "product_id": 0x1085, "usage_page": 0xFF03, "usage": 0, "path": b"b3"},
        {"vendor_id": 0x373B, "product_id": 0x1085, "usage_page": 0x0001, "usage": 2, "path": b"bm"},
        {"vendor_id": 0x046D, "product_id": 0xC547, "usage_page": 0xFF00, "usage": 2, "path": b"logi"},
    ]
    assert candidate_paths(hid_list) == {"3554:f58e": [(0xFF02, b"a2"), (0xFF05, b"a5")],
                                         "373b:1085": [(0xFF03, b"b3"), (0xFF04, b"b4")]}

    # รายงาน: VID:PID จาก key ของแต่ละแหล่ง
    assert [usb_key({"key": k}) for k in ("3554:f58e", "usb:040b:0897", "logi:c547:1", "hc:0x1038:0x12ad",
                                          "bt:WH-1000XM4", "none")] == ["3554:f58e", "040b:0897", "046d:c547",
                                                                        "1038:12ad", None, None]
    q = parse_qs(urlparse(issue_url("9.9.9", ["- x"], ["✅ a"])).query)
    assert q["hid"] == ["✅ a"] and "hid" not in parse_qs(urlparse(issue_url("9.9.9", ["- x"])).query)

    # สแกนอุปกรณ์: รวม collection ต่ออุปกรณ์, สถานะ ok/found/unsupported, ข้ามอุปกรณ์ HID มาตรฐาน
    scan_hid = [dict(d, product_string="VK 75 Wireless Receiver", manufacturer_string="") for d in hid_list[2:5]] + [
        {"vendor_id": 0x3554, "product_id": 0xF58E, "usage_page": 0xFF02, "usage": 2, "path": b"a2",
         "product_string": "2.4G Wireless Receiver", "manufacturer_string": "Compx"},
        {"vendor_id": 0x1234, "product_id": 0x0001, "usage_page": 0x0001, "usage": 6, "path": b"kbd",
         "product_string": "HID Keyboard", "manufacturer_string": ""},
        {"vendor_id": 0x25A7, "product_id": 0xFA70, "usage_page": 0xFF00, "usage": 1, "path": b"nk",
         "product_string": "NK mouse NANO dongle", "manufacturer_string": ""}]
    groups = group_hid(scan_hid)
    assert groups["373b:1085"]["pages"] == [(0xFF04, 2), (0xFF03, 0), (0x0001, 2)] and groups["373b:1085"]["paths"][0xFF03] == b"b3"
    devs = [{"key": "3554:f58e", "name": "เมาส์"}, {"key": "373b:1085", "name": "อุปกรณ์ 2.4G"},
            {"key": "usb:040b:0897", "name": "หูฟัง", "no_battery": True}, {"key": "bt:Buds", "name": "Buds"}]
    entries = build_entries(groups, devs, {"3554:f58e": (80, False), "bt:Buds": (55, True)},
                            {("373b:1085", 0xFF03): "0603ff" * 50, ("25a7:fa70", 0xFF00): "06"})
    got = [(e["key"], e["status"]) for e in entries]
    assert got == [("bt:Buds", "ok"), ("3554:f58e", "ok"), ("040b:0897", "info"), ("373b:1085", "found"),
                   ("25a7:fa70", "unsupported")], got
    lines = scan_lines(entries, max_desc=4)
    assert lines[0].startswith("✅ `bt:Buds`") and any("❔ `25a7:fa70` NK mouse NANO dongle" in x for x in lines)
    assert "    page 0xff03 usage 0x0000 desc 0603ff06…" in lines and "    page 0xff00 usage 0x0001 desc 06" in lines
    assert not any("1234:0001" in x for x in lines)                      # คีย์บอร์ด HID มาตรฐานไม่อยู่ในรายงาน
    assert scan_lines([]) == ["(ไม่พบอุปกรณ์)"]

    # อัปเดตตัวเอง: สลับไฟล์ได้, ถ้าวางไฟล์ใหม่ไม่ได้ต้องคืนตัวเดิม, ไฟล์โหลดไม่ครบต้องถูกปฏิเสธ
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        target, new = d / EXE_NAME, d / (EXE_NAME + ".new")
        target.write_bytes(b"MZ old")
        new.write_bytes(b"MZ new")
        swap_exe(target, new)
        assert target.read_bytes() == b"MZ new" and (d / (EXE_NAME + ".old")).read_bytes() == b"MZ old"
        target.write_bytes(b"MZ cur")
        try:
            swap_exe(target, d / "missing.exe")
        except OSError:
            pass
        assert target.read_bytes() == b"MZ cur"
        src = d / "src.exe"
        src.write_bytes(b"MZ" + b"x" * 10)
        download_update(src.as_uri(), 12, d / "ok.exe")
        assert (d / "ok.exe").read_bytes()[:2] == b"MZ"
        for bad_size in (11, 13):
            try:
                download_update(src.as_uri(), bad_size, d / "bad.exe")
                raise AssertionError("ขนาดไม่ตรงต้องถูกปฏิเสธ")
            except ValueError:
                assert not (d / "bad.exe").exists() and not (d / "bad.exe.part").exists()

    # อุปกรณ์ไม่ส่งค่าแบต: ขึ้นเมื่อเคยเสียบ, บอกสถานะเสียบ/ถอดถูกต้อง
    real_present = nobattery.present_usb_keys
    try:
        nobattery.present_usb_keys = lambda: set()  # noqa: E731
        assert nobattery_devices({}) == []
        nobattery.present_usb_keys = lambda: {"040b:0897", "3554:f58e"}  # noqa: E731
        c = {}
        (hs,) = nobattery_devices(c)
        assert hs["kind"] == "headset" and hs["connected"]() and c["seen_nobat"] == ["040b:0897"]
        nobattery.present_usb_keys = lambda: set()  # noqa: E731
        (hs,) = nobattery_devices(c)
        assert not hs["connected"]()
    finally:
        nobattery.present_usb_keys = real_present

    # Compx: คำตอบจริงจาก capture / อุปกรณ์
    assert mouse_frame().hex() == "0804000000000000000000000000000049"
    assert mouse_parse(bytes.fromhex("0804000000026400104c00000000000087")) == (100, False)
    assert mouse_parse(bytes.fromhex("0804010000000000000000000000000048")) is None
    assert kb_frame().hex() == "134a01000000000000000000000000000000005e"
    assert kb_parse(bytes.fromhex("134a0100025201000000000000000000000000b3")) == (82, None)

    # Logitech: จำลองอุปกรณ์ HID++ ที่ index 1 มี 0x1004 อยู่ที่ feature index 0x08
    class FakeLogi:
        def __init__(self):
            self.out = []

        def write(self, p):
            idx, feat, fnsw = p[1], p[2], p[3]
            if idx != 1:
                self.out.append(bytes([0x10, idx, 0x8F, feat, fnsw, 0x09, 0]))
            elif feat == 0 and p[4:6] == b"\x10\x04":
                self.out.append(bytes([0x11, 1, 0, fnsw, 0x08]).ljust(20, b"\0"))
            elif feat == 0:
                self.out.append(bytes([0x11, 1, 0, fnsw, 0x00]).ljust(20, b"\0"))
            elif feat == 0x08:
                self.out.append(bytes([0x11, 1, 0x08, fnsw, 57, 0x04, 0x01]).ljust(20, b"\0"))
            return len(p)

        def read(self, n, t):
            return list(self.out.pop(0)) if self.out else []

    fake = FakeLogi()
    assert logi_battery(fake, 1) == (57, True)
    assert logi_battery(fake, 2) is None
    assert volt_to_pct(4200) == 100 and volt_to_pct(3800) == 50 and volt_to_pct(3300) == 0

    # HeadsetControl: รูปแบบ JSON ของ headsetcontrol -o json
    hc = headsetcontrol_parse(json.dumps({"devices": [
        {"device": "SteelSeries Arctis 7", "id_vendor": "0x1038", "id_product": "0x12ad",
         "battery": {"status": "BATTERY_CHARGING", "level": 64}},
        {"device": "HyperX Cloud", "id_vendor": "0x0951", "id_product": "0x16c4",
         "battery": {"status": "BATTERY_UNAVAILABLE", "level": -1}}]}))
    assert hc["hc:0x1038:0x12ad"] == ("SteelSeries Arctis 7", (64, True))
    assert hc["hc:0x0951:0x16c4"] == ("HyperX Cloud", None)
    assert headsetcontrol_parse("not json") == {}

    sys.stdout.reconfigure(encoding="utf-8")
    for dev in discover(load_cache()):
        if dev.get("no_battery"):
            print(f"{dev['name']}: " + ("เชื่อมต่ออยู่ (ไม่ส่งค่าแบต)" if dev["connected"]() else "ไม่ได้เสียบ"))
            continue
        print(tooltip(dev["name"], dev["read"]()))
