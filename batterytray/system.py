"""ติดตั้งไว้ที่ถาวร, เปิดพร้อม Windows, เปิดตัวเองใหม่, กันเปิดซ้ำ"""
from pathlib import Path
import os
import shutil
import subprocess
import sys
from batterytray.config import APP_DIR, DATA_DIR, EXE_NAME, FROZEN, NO_WINDOW, log_error
from batterytray.updater import swap_exe


# ---------- ติดตั้งไว้ที่ถาวร ----------

INSTALL_DIR = Path(os.environ.get("LOCALAPPDATA", str(DATA_DIR))) / "BatteryTray"


def same_dir(a, b):
    """เทียบโฟลเดอร์ทั้งแบบตรงตัวและแบบตาม link/redirect — ตรงแบบใดแบบหนึ่งถือว่าเป็นที่เดียวกัน
    (resolve() อย่างเดียวพลาดได้ เช่น โปรเซสในแพ็กเกจ MSIX ที่ %LOCALAPPDATA% ถูก redirect)"""
    norm = lambda p: os.path.normcase(os.path.abspath(p))  # noqa: E731
    return norm(a) == norm(b) or norm(Path(a).resolve()) == norm(Path(b).resolve())


def needs_install():
    if not FROZEN or "--installed-from" in sys.argv:  # เพิ่งถูกติดตั้งมา — ห้ามติดตั้งซ้ำ (กันวนไม่รู้จบ)
        return False
    return not same_dir(Path(sys.executable).parent, INSTALL_DIR)


def install_copy(src, dest):
    """คัดลอก src ไปที่ dest (แทนตัวเดิมถ้ามี โดยคืนตัวเดิมถ้าล้มเหลว)"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        shutil.copy2(src, dest)
        return
    new = dest.with_name(dest.name + ".new")
    shutil.copy2(src, new)
    swap_exe(dest, new)



# ---------- ตั้งค่า ----------

STARTUP_LNK = Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs\Startup\Battery Tray.lnk"


def launch_cmd():
    """คำสั่งเปิดแอปนี้แบบไม่มีหน้าต่าง console"""
    if FROZEN:
        return [sys.executable]
    return [str(Path(sys.executable).with_name("pythonw.exe")), str(APP_DIR / "battery_monitor.py")]


def relaunch_env():
    """env สำหรับเปิดตัวเองใหม่ — ตัวใหม่ต้องแตกไฟล์เอง ไม่ใช้โฟลเดอร์ชั่วคราวของตัวเก่า
    (ไม่งั้นพอตัวเก่าปิด โฟลเดอร์ถูกลบ → 'Failed to import encodings module' / หา USB ไม่เจอ)"""
    env = dict(os.environ)
    if FROZEN:
        env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


def set_startup(on, exe=None):
    if not on:
        STARTUP_LNK.unlink(missing_ok=True)
        return
    target, *args = [str(exe)] if exe else launch_cmd()
    ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:LNK);"
          "$s.TargetPath=$env:TARGET; $s.Arguments=$env:ARGS;"
          "$s.WorkingDirectory=$env:DIR; $s.Description='Battery Tray'; $s.Save()")
    env = dict(os.environ, LNK=str(STARTUP_LNK), TARGET=target, DIR=str(Path(exe).parent if exe else APP_DIR),
               ARGS=" ".join(f'"{a}"' for a in args))
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], env=env, creationflags=NO_WINDOW)



MUTEX_NAME = "Local\\BatteryTray.SingleInstance"
WAIT_FLAG = "--wait-previous"  # เปิดตัวเองใหม่ (อัปเดต/ค้นหาใหม่/ติดตั้ง) — รอตัวเก่าปิดแทนการถูกบล็อก
_mutex = None  # ถือไว้ตลอดอายุโปรเซส; Windows ปล่อยให้เองตอนปิด (แม้โปรเซสตาย)


def acquire_single_instance(wait_s=0, name=MUTEX_NAME):
    """True ถ้าเป็นตัวเดียวในเครื่อง (named mutex ของ Windows — ไม่ขึ้นกับจังหวะเวลา)"""
    global _mutex
    import ctypes
    k = ctypes.windll.kernel32
    k.CreateMutexW.restype = ctypes.c_void_p
    handle = k.CreateMutexW(None, False, name)
    if not handle:
        return True  # สร้างไม่ได้ — ไม่บล็อกการใช้งาน
    r = k.WaitForSingleObject(ctypes.c_void_p(handle), int(wait_s * 1000))
    if r in (0, 0x80):  # WAIT_OBJECT_0 / WAIT_ABANDONED (ตัวเก่าตายโดยไม่ปล่อย)
        _mutex = handle
        return True
    k.CloseHandle(ctypes.c_void_p(handle))
    return False


def relaunch(cmd, cwd, *args):
    """เปิดตัวเองใหม่ — ตัวใหม่จะรอ mutex จนตัวนี้ปิด"""
    subprocess.Popen([*cmd, *args, WAIT_FLAG], cwd=cwd, env=relaunch_env())


def self_install():
    """เปิดจากที่อื่น (เช่น Downloads) → คัดลอกไป INSTALL_DIR, ตั้งเปิดพร้อม Windows, เปิดตัวนั้นแทน
    คืน True ถ้าตัวนี้ควรปิด (ส่งต่อให้ตัวที่ติดตั้งแล้ว)"""
    dest = INSTALL_DIR / EXE_NAME
    try:
        install_copy(Path(sys.executable), dest)
        set_startup(True, exe=dest)
        relaunch([str(dest)], dest.parent, "--installed-from", sys.executable)
        return True
    except Exception:
        log_error("self-install")
        return False  # ใช้งานต่อจากที่เดิม
