"""แอป tray: อ่านค่าเป็นรอบ, ไอคอน, แจ้งเตือน, เมนู"""
from pathlib import Path
import pystray
import sys
import threading
import time
from batterytray.config import (APP_DIR, DATA_DIR, DEFAULTS, ERROR_LOG, FROZEN, RELEASES_PAGE, UPDATE_EVERY_S, VERSION,
                                load_cache, log_error, save_cache)
from batterytray.devices import discover
from batterytray.history import estimate_remaining_h, fmt_remaining, record_history
from batterytray.report import device_lines, hid_inventory, issue_url, known_usb_keys
from batterytray.icons import make_icon, taskbar_is_light, tooltip
from batterytray.settings_ui import settings_window
from batterytray.system import INSTALL_DIR, WAIT_FLAG, acquire_single_instance, launch_cmd, needs_install, relaunch, self_install
from batterytray.updater import cleanup_old_exe, download_update, is_newer, latest_release, swap_exe


def app():
    if not acquire_single_instance(wait_s=20 if WAIT_FLAG in sys.argv else 0):
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, "Battery Tray เปิดอยู่แล้ว — ดูที่ไอคอน % ข้างนาฬิกา\n"
                                         "(ถ้าไม่เห็น ให้กดลูกศร ^ บนแถบงาน)", "Battery Tray", 0x40)
        return
    if needs_install():
        cleanup_old_exe()  # อัปเดตจาก v1.4.x ที่ Downloads ทิ้ง .old ไว้ — ลบก่อนย้ายไปที่ถาวร
        if self_install():
            return
    installed_from = sys.argv[sys.argv.index("--installed-from") + 1] if "--installed-from" in sys.argv else None
    threading.Thread(target=cleanup_old_exe, daemon=True).start()
    cache = load_cache()
    first_run = "settings" not in cache
    settings = {**DEFAULTS, **cache.get("settings", {})}
    cache["settings"] = settings
    last = cache.setdefault("last", {})
    all_devices = discover(cache)
    devices = [d for d in all_devices if not d.get("no_battery")] or [
        {"key": "none", "kind": None, "name": "ไม่พบอุปกรณ์ที่รองรับ", "read": lambda: None}]
    save_cache(cache)
    stop, wake, lock, settings_open = threading.Event(), threading.Event(), threading.Lock(), threading.Lock()
    alerted, full_notified = set(), set()
    history = cache.setdefault("history", {})
    icons = []

    def label(dev):
        return settings["names"].get(dev["key"], dev["name"])

    def refresh():
        with lock:
            light = taskbar_is_light()
            for dev, icon in zip(devices, icons):
                icon.visible = dev["key"] not in settings["hidden"]
                try:
                    res = dev["read"]()
                except Exception:
                    log_error(f"read {dev['key']}")
                    res = None
                name = label(dev)
                if res:
                    dev["stale"] = False
                    prev = last.get(dev["key"])
                    last[dev["key"]] = [list(res), time.strftime("%d/%m %H:%M")]
                    hist = history.setdefault(dev["key"], [])
                    record_history(hist, time.time(), res[0], res[1])
                    eta = None if res[1] else fmt_remaining(estimate_remaining_h(hist, time.time()))
                    icon.icon, icon.title = make_icon(res, light=light), tooltip(name, res, eta)
                    was_charging = bool(prev and prev[0][1])
                    full = res[0] >= 100 and (res[1] or was_charging)
                    if full and dev["key"] not in full_notified:
                        if settings.get("notify_full", True):
                            icon.notify(f"{name} ชาร์จเต็มแล้ว — ถอดสายได้เลย", "ชาร์จเต็ม")
                        full_notified.add(dev["key"])
                    elif not res[1] and res[0] < 100:
                        full_notified.discard(dev["key"])
                    low = bool(settings["alert"]) and res[0] <= settings["alert"] and not res[1]
                    if low and dev["key"] not in alerted:
                        icon.notify(f"{name} เหลือ {res[0]}% — ควรชาร์จ", "แบตใกล้หมด")
                        alerted.add(dev["key"])
                    elif not low:
                        alerted.discard(dev["key"])
                elif dev["key"] in last:
                    dev["stale"] = True
                    old, at = last[dev["key"]]
                    icon.icon = make_icon(old, stale=True, light=light)
                    icon.title = f"{name}: {old[0]}% (ค่าล่าสุด {at}, ตอนนี้หลับอยู่)"
                else:
                    icon.icon, icon.title = make_icon(None, light=light), tooltip(name, None)
            save_cache(cache)

    def open_settings(*_):
        if not settings_open.acquire(blocking=False):
            return  # เปิดอยู่แล้ว

        def run():
            try:
                settings_window(all_devices, settings, last, on_save=wake.set, history=history)
            finally:
                settings_open.release()
        threading.Thread(target=run, daemon=True).start()

    def quit_all(*_):
        stop.set()
        wake.set()
        for icon in icons:
            icon.stop()

    def rescan(*_):
        # ponytail: เริ่มโปรเซสใหม่แทนการเพิ่ม/ลบไอคอนสด ๆ
        cache.pop("kinds", None)
        cache.pop("logi", None)
        save_cache(cache)
        relaunch(launch_cmd(), APP_DIR)
        quit_all()

    update = {}

    def check_update(manual=False, startup=False):
        if not (manual or startup) and time.time() - cache.get("update_checked", 0) < UPDATE_EVERY_S:
            return
        cache["update_checked"] = time.time()
        save_cache(cache)
        rel = latest_release()
        if not rel:
            if manual:
                icons[0].notify("เช็คอัปเดตไม่ได้ — ตรวจการเชื่อมต่ออินเทอร์เน็ตแล้วลองใหม่", "เช็คอัปเดต")
            return
        if not is_newer(rel["tag"], VERSION):
            if manual:
                icons[0].notify(f"ใช้เวอร์ชันล่าสุดแล้ว (v{VERSION})", "เช็คอัปเดต")
            return
        update.update(rel)
        for icon in icons:
            icon.update_menu()
        if manual or cache.get("update_notified") != rel["tag"]:
            cache["update_notified"] = rel["tag"]
            save_cache(cache)
            icons[0].notify(f"Battery Tray {rel['tag']} พร้อมแล้ว — คลิกขวาที่ไอคอน → {update_label()}", "มีเวอร์ชันใหม่")

    def can_self_update():
        return FROZEN and bool(update.get("asset_url")) and isinstance(update.get("asset_size"), int)

    def update_label(*_):
        verb = "อัปเดตเป็น" if can_self_update() else "ดาวน์โหลด"
        return f"{verb} {update.get('tag')} ตอนนี้" if can_self_update() else f"{verb}เวอร์ชันใหม่ ({update.get('tag')})"

    def report_issue(*_):
        """เปิดหน้า New Issue (กรอกเวอร์ชัน + อุปกรณ์ให้แล้ว) และโฟลเดอร์ log ถ้ามี error.log ให้ลากแนบ"""
        import os
        import webbrowser
        try:
            import hid
            inventory = hid_inventory(hid.enumerate(), known_usb_keys(all_devices))
        except Exception:
            log_error("hid inventory")
            inventory = None
        webbrowser.open(issue_url(VERSION, device_lines(all_devices, last, label), inventory))
        if ERROR_LOG.exists():
            os.startfile(DATA_DIR)

    def open_release_page():
        import webbrowser
        webbrowser.open(update.get("url", RELEASES_PAGE))

    def run_update():
        target = Path(sys.executable)
        new = target.with_name(target.name + ".new")
        try:
            icons[0].notify(f"กำลังดาวน์โหลด {update['tag']}...", "กำลังอัปเดต")
            download_update(update["asset_url"], update["asset_size"], new)
            swap_exe(target, new)
        except Exception:
            log_error("self-update")
            new.unlink(missing_ok=True)
            icons[0].notify("อัปเดตอัตโนมัติไม่สำเร็จ — เปิดหน้าดาวน์โหลดให้แล้ว", "อัปเดตไม่สำเร็จ")
            open_release_page()
            return
        relaunch([str(target)], target.parent)
        quit_all()

    def on_update(*_):
        if can_self_update():
            threading.Thread(target=run_update, daemon=True).start()
        else:
            open_release_page()

    menu = pystray.Menu(pystray.MenuItem(update_label, on_update, visible=lambda _: bool(update)),
                        pystray.MenuItem("ตั้งค่า...", open_settings, default=True),
                        pystray.MenuItem("รีเฟรช", lambda *_: wake.set()),
                        pystray.MenuItem("ค้นหาอุปกรณ์ใหม่", rescan),
                        pystray.MenuItem("เช็คอัปเดต",
                                         lambda *_: threading.Thread(target=check_update, args=(True,), daemon=True).start()),
                        pystray.MenuItem("รายงานปัญหา / แจ้งอุปกรณ์", report_issue),
                        pystray.Menu.SEPARATOR,
                        pystray.MenuItem("ปิด", quit_all))
    for dev in devices:
        old = last.get(dev["key"])
        start = make_icon(old[0] if old else None, stale=bool(old), light=taskbar_is_light())
        icons.append(pystray.Icon("battery_" + dev["key"], start, label(dev), menu))
    for icon in icons[1:]:
        icon.run_detached()

    def loop():
        nonlocal installed_from
        show_first = first_run
        show_startup_check = True
        while not stop.is_set():
            refresh()
            check_update(startup=show_startup_check)
            show_startup_check = False
            if show_first:
                show_first = False
                open_settings()
            if installed_from:
                icons[0].notify(f"ติดตั้งไว้ที่ {INSTALL_DIR} และตั้งให้เปิดพร้อม Windows แล้ว — "
                                f"ลบไฟล์เดิม ({Path(installed_from).name} ใน {Path(installed_from).parent.name}) ได้เลย",
                                "ติดตั้งเรียบร้อย")
                installed_from = None
            wake.wait(settings["interval"])
            wake.clear()

    threading.Thread(target=loop, daemon=True).start()
    icons[0].run()
