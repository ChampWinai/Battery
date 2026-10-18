"""ประวัติแบต, ประมาณเวลาที่เหลือ, พิกัดกราฟ"""

# ---------- ประวัติแบต + ประมาณเวลาที่เหลือ ----------

HISTORY_DAYS = 7
MIN_SPAN_H, MIN_DROP = 2, 3  # ต้องมีข้อมูลอย่างน้อย 2 ชม. และแบตลด ≥3% ถึงจะประมาณ (กันตัวเลขมั่ว)


def record_history(hist, ts, pct, charging):
    """เก็บ [ts, pct, charging] เมื่อค่าเปลี่ยน หรือทุก 30 นาที — เก็บย้อนหลัง 7 วัน"""
    if not hist or hist[-1][1] != pct or hist[-1][2] != bool(charging) or ts - hist[-1][0] >= 1800:
        hist.append([ts, pct, bool(charging)])
    cutoff = ts - HISTORY_DAYS * 86400
    while hist and hist[0][0] < cutoff:
        hist.pop(0)


def estimate_remaining_h(hist, now):
    """ชั่วโมงที่เหลือจากอัตราลดของช่วงคายประจุล่าสุด (ตั้งแต่ชาร์จครั้งก่อน) หรือ None ถ้าข้อมูลยังไม่พอ"""
    seg = []
    for ts, pct, chg in reversed(hist):
        if chg or (seg and pct < seg[-1][1]):  # เจอช่วงชาร์จ / แบตเพิ่มขึ้น = จบช่วงคายประจุ
            break
        seg.append((ts, pct))
    if len(seg) < 2:
        return None
    (t1, p1), (t0, p0) = seg[0], seg[-1]
    span_h, drop = (t1 - t0) / 3600, p0 - p1
    if span_h < MIN_SPAN_H or drop < MIN_DROP:
        return None
    return max(0.0, p1 / (drop / span_h) - (now - t1) / 3600)


def history_points(hist, now, w, h, pad=4):
    """แปลงประวัติเป็นพิกัดกราฟ → (pts [(x, y, charging)], span_s)
    แกน x เริ่มที่จุดแรกที่มี (ไม่เกิน 7 วัน, อย่างน้อย 1 ชม.) ถึงตอนนี้; y = % (บน=100)"""
    recent = [r for r in hist if r[0] >= now - HISTORY_DAYS * 86400]
    span = min(HISTORY_DAYS * 86400, max(3600, now - recent[0][0])) if recent else 3600
    t0 = now - span
    pts = [(round(pad + (ts - t0) / span * (w - 2 * pad), 1),
            round(pad + (100 - max(0, min(100, pct))) / 100 * (h - 2 * pad), 1), bool(chg))
           for ts, pct, chg in recent if ts >= t0]
    return pts, span


def fmt_span(span):
    return f"{round(span / 3600)} ชม.ก่อน" if span < 86400 else f"{round(span / 86400)} วันก่อน"


def fmt_remaining(h):
    if h is None:
        return None
    if h < 1:
        return "ไม่ถึง 1 ชม."
    return f"~{round(h)} ชม." if h < 48 else f"~{round(h / 24)} วัน"
