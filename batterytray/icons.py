"""ไอคอน % บน taskbar"""
from PIL import Image
from PIL import ImageDraw
from PIL import ImageFont


# ---------- ไอคอน ----------

def level_color(pct):
    return (239, 68, 68) if pct <= 20 else (245, 158, 11) if pct <= 40 else (34, 197, 94)


def taskbar_is_light():
    """True ถ้า taskbar ใช้ธีมสว่าง (Settings → Personalization → Colors)"""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return winreg.QueryValueEx(k, "SystemUsesLightTheme")[0] == 1
    except OSError:
        return False


def make_icon(res, stale=False, light=False):
    """ไอคอน 64px: ตัวเลข % ใหญ่ + แถบระดับแบตด้านล่าง + สายฟ้าถ้าชาร์จ
    light=True → ตัวเลขสีเข้มสำหรับ taskbar ธีมสว่าง"""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    ok = isinstance(res, (tuple, list))
    pct = res[0] if ok else 0
    text = str(pct) if ok else "--"
    font = ImageFont.truetype("segoeuib.ttf", 40 if len(text) >= 3 else 54)
    if light:
        fill, stroke, track, gray = ((110, 110, 110) if stale else (17, 24, 39)), (255, 255, 255), (200, 205, 212), (150, 150, 150)
    else:
        fill, stroke, track, gray = ((160, 160, 160) if stale else (255, 255, 255)), (0, 0, 0), (70, 70, 70), (140, 140, 140)
    d.text((32, 26), text, font=font, fill=fill, anchor="mm", stroke_width=2, stroke_fill=stroke)
    d.rectangle((0, 54, 63, 63), fill=track)
    if ok:
        color = gray if stale else level_color(pct)
        d.rectangle((0, 54, max(6, 64 * pct // 100) - 1, 63), fill=color)
        if res[1]:
            d.polygon([(52, 0), (44, 14), (50, 14), (46, 26), (60, 10), (53, 10), (58, 0)],
                      fill=(234, 179, 8) if light else (255, 220, 0), outline=(120, 90, 0) if light else None)
    return img


def tooltip(name, res, eta=None):
    if not isinstance(res, (tuple, list)):
        return f"{name}: หลับอยู่ (ขยับ/กดปุ่มแล้วรีเฟรช)"
    return f"{name}: {res[0]}%" + (" กำลังชาร์จ" if res[1] else "") + (f" · เหลือ {eta}" if eta else "")
