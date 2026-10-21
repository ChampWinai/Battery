"""หน้าต่างตั้งค่า + กราฟประวัติ (customtkinter)"""
import time
from batterytray.config import VERSION
from batterytray.devices.headsetcontrol import HEADSETCONTROL_URL, headsetcontrol_exe
from batterytray.history import estimate_remaining_h, fmt_remaining, fmt_span, history_points
from batterytray.icons import level_color
from batterytray.system import STARTUP_LNK, set_startup


def work_area_height(root):
    """ความสูงจอที่ใช้ได้จริง (หัก taskbar) — fallback เป็นความสูงจอ"""
    try:
        import ctypes
        r = (ctypes.c_long * 4)()
        if ctypes.windll.user32.SystemParametersInfoW(0x30, 0, r, 0):  # SPI_GETWORKAREA
            return r[3] - r[1]
    except Exception:
        pass
    return root.winfo_screenheight()


def settings_window(devices, settings, last, on_save, history=None, on_scan=None, on_report=None, on_rescan=None,
                    open_scan=False):
    """หน้าต่างตั้งค่า (customtkinter ใน thread ของตัวเอง)
    ดีไซน์: ui-ux-pro-max — Dark slate + status green, สถานะมีข้อความกำกับ (ไม่ใช้สีอย่างเดียว)"""
    import webbrowser

    import customtkinter as ctk

    C = {"bg": "#0F172A", "card": "#1B2336", "muted": "#272F42", "line": "#2B3548", "border": "#475569",
         "text": "#F8FAFC", "sub": "#94A3B8", "accent": "#22C55E", "on_accent": "#0F172A",
         "accent_hover": "#16A34A", "danger": "#EF4444"}
    TH = "Leelawadee UI"
    GLYPH = {"mouse": "", "keyboard": "", "headset": "", None: ""}  # Segoe MDL2 Assets

    def hexc(rgb):
        return "#%02x%02x%02x" % rgb

    def status_of(old, stale):
        """(ข้อความ, สี) — ข้อความกำกับเสมอ ไม่พึ่งสีอย่างเดียว"""
        if not old:
            return "ยังไม่ทราบค่า", C["sub"]
        pct, chg = old[0]
        if stale:
            return f"หลับอยู่ · ค่าล่าสุด {old[1]}", C["sub"]
        if chg:
            return "⚡ กำลังชาร์จ", C["accent"]
        if pct <= 20:
            return "วิกฤต · ควรชาร์จ", hexc(level_color(pct))
        if pct <= 40:
            return "ต่ำ", hexc(level_color(pct))
        return "ปกติ", hexc(level_color(pct))

    def focus_ring(entry):
        entry.bind("<FocusIn>", lambda _: entry.configure(border_color=C["accent"]))
        entry.bind("<FocusOut>", lambda _: entry.configure(border_color=C["card"]))

    ctk.set_appearance_mode("dark")
    root = ctk.CTk(fg_color=C["bg"])
    root.title("Battery Tray")
    root.resizable(False, False)
    root.attributes("-topmost", True)
    body = ctk.CTkFrame(root, fg_color=C["bg"])
    body.pack(padx=24, pady=16, fill="both")

    # ---- ส่วนหัว: ชื่อแอป + สรุปภาพรวม ----
    shown = [d for d in devices if d["key"] != "none"]
    known = [last[d["key"]][0][0] for d in shown if d["key"] in last]
    head = ctk.CTkFrame(body, fg_color="transparent")
    head.pack(fill="x")
    ctk.CTkLabel(head, text="Battery Tray", font=(TH, 24, "bold"), text_color=C["text"]).pack(side="left")
    ctk.CTkLabel(head, text=f"v{VERSION}", font=(TH, 12), text_color=C["sub"]).pack(side="left", padx=8, pady=(8, 0))
    if on_scan:
        ctk.CTkButton(head, text="สแกนอุปกรณ์", width=104, height=30, corner_radius=8, font=(TH, 12),
                      fg_color=C["muted"], hover_color=C["line"], text_color=C["text"], cursor="hand2",
                      command=lambda: show_scan()).pack(side="right")
    summary = f"{len(shown)} อุปกรณ์" + (f"  ·  ต่ำสุด {min(known)}%" if known else "")
    ctk.CTkLabel(body, text=summary, font=(TH, 13), text_color=C["sub"]).pack(anchor="w", pady=(0, 10))

    def draw_graph(parent, key):
        """กราฟ % ย้อนหลัง (สูงสุด 7 วัน) — เส้นเขียว, จุดเหลือง = ช่วงชาร์จ"""
        import tkinter as tk
        w, h, left, bottom = 460, 200, 34, 20
        cv = tk.Canvas(parent, width=w, height=h, bg=C["card"], highlightthickness=0)
        hist = list((history or {}).get(key, []))
        if hist:  # ค่าล่าสุดยังเป็นจริงจนถึงตอนนี้ — ลากเส้นต่อถึงขอบขวา
            hist.append([time.time(), hist[-1][1], hist[-1][2]])
        pts, span = history_points(hist, time.time(), w - left, h - bottom)
        for pct in (0, 25, 50, 75, 100):
            y = 4 + (100 - pct) / 100 * (h - bottom - 8)
            cv.create_line(left, y, w - 4, y, fill=C["line"])
            cv.create_text(left - 4, y, text=f"{pct}%", fill=C["sub"], font=(TH, 9), anchor="e")
        cv.create_text(left, h - 8, text=fmt_span(span), fill=C["sub"], font=(TH, 9), anchor="w")
        cv.create_text(w - 4, h - 8, text="ตอนนี้", fill=C["sub"], font=(TH, 9), anchor="e")
        pts = [(x + left - 4, y, chg) for x, y, chg in pts]
        if len(pts) < 2:
            cv.create_text((w + left) / 2, (h - bottom) / 2, fill=C["sub"], font=(TH, 12),
                           text="ยังมีข้อมูลไม่พอ\nแอปจะเก็บค่าทุกครั้งที่ % เปลี่ยน", justify="center")
        else:
            cv.create_line(*[c for x, y, _ in pts for c in (x, y)], fill=C["accent"], width=2)
            for x, y, chg in pts:
                if chg:
                    cv.create_oval(x - 3, y - 3, x + 3, y + 3, fill="#EAB308", outline="")
        return cv

    graph_win = {}  # เปิดได้ทีละหน้าต่าง
    scan_win = {}

    def show_scan():
        """หน้าต่างสแกน: รันสแกนใน thread แยก แล้วแสดงสถานะทุกอุปกรณ์ + ปุ่มส่งผล"""
        import threading
        if scan_win.get("w") is not None and scan_win["w"].winfo_exists():
            scan_win["w"].focus_force()
            return
        top = ctk.CTkToplevel(root, fg_color=C["bg"])
        top.title("สแกนอุปกรณ์")
        top.resizable(False, False)
        top.attributes("-topmost", True)
        scan_win["w"] = top
        ctk.CTkLabel(top, text="สแกนอุปกรณ์", font=(TH, 18, "bold"), text_color=C["text"]).pack(anchor="w", padx=18, pady=(14, 0))
        ctk.CTkLabel(top, text="อุปกรณ์ HID ทั้งหมดในเครื่อง · ส่งคำสั่งเฉพาะยี่ห้อที่รู้วิธีอ่านแบตแล้ว",
                     font=(TH, 12), text_color=C["sub"]).pack(anchor="w", padx=18, pady=(0, 8))
        listbox = ctk.CTkScrollableFrame(top, width=460, height=300, fg_color=C["card"], corner_radius=16)
        listbox.pack(padx=16, pady=(0, 8))
        status = ctk.CTkLabel(top, text="กำลังสแกน ~15 วินาที... ขยับเมาส์และกดปุ่มคีย์บอร์ดไว้ระหว่างนี้",
                              font=(TH, 12), text_color=C["sub"])
        status.pack(anchor="w", padx=18)
        bar = ctk.CTkFrame(top, fg_color="transparent")
        bar.pack(fill="x", padx=16, pady=(8, 14))
        state = {}

        def btn(text, cmd, primary=False):
            return ctk.CTkButton(bar, text=text, height=36, corner_radius=10, font=(TH, 13, "bold" if primary else "normal"),
                                 fg_color=C["accent"] if primary else "transparent", border_width=0 if primary else 1,
                                 border_color=C["border"], hover_color=C["accent_hover"] if primary else C["muted"],
                                 text_color=C["on_accent"] if primary else C["text"], cursor="hand2", command=cmd)

        send_btn = btn("ส่งผลสแกน", lambda: on_report and threading.Thread(
            target=on_report, args=(state.get("entries"),), daemon=True).start(), primary=True)
        again_btn = btn("สแกนใหม่", lambda: start())
        add_btn = btn("เพิ่มลงแถบงาน", lambda: (top.destroy(), root.destroy(), on_rescan and on_rescan()))
        send_btn.pack(side="right")
        again_btn.pack(side="right", padx=(0, 8))

        def render(entries, new_found):
            for w in listbox.winfo_children():
                w.destroy()
            icon = {"ok": ("✅", C["accent"]), "info": ("ℹ", C["sub"]), "found": ("⚠", "#F59E0B"),
                    "unsupported": ("❔", C["sub"])}
            for e in entries:
                row = ctk.CTkFrame(listbox, fg_color="transparent")
                row.pack(fill="x", pady=4, padx=4)
                mark, color = icon[e["status"]]
                ctk.CTkLabel(row, text=mark, font=(TH, 15), text_color=color, width=26).pack(side="left", anchor="n")
                col = ctk.CTkFrame(row, fg_color="transparent")
                col.pack(side="left", fill="x", expand=True)
                ctk.CTkLabel(col, text=f"{e['name']}  ·  {e['key']}", font=(TH, 13, "bold"), text_color=C["text"],
                             anchor="w", justify="left", wraplength=400).pack(anchor="w")
                ctk.CTkLabel(col, text=e["detail"], font=(TH, 12), text_color=C["sub"], anchor="w", justify="left",
                             wraplength=400).pack(anchor="w")
            if not entries:
                ctk.CTkLabel(listbox, text="ไม่พบอุปกรณ์", font=(TH, 13), text_color=C["sub"]).pack(pady=20)
            counts = {k: sum(e["status"] == k for e in entries) for k in ("ok", "info", "found", "unsupported")}
            parts = [f"อ่านได้ {counts['ok']}"] + [f"{label} {counts[k]}" for k, label in
                                                (("found", "อ่านไม่ได้"), ("unsupported", "ยังไม่รองรับ"), ("info", "ไม่ส่งค่าแบต"))
                                                if counts[k]]
            hint = "  —  ส่งผลสแกนช่วยให้รองรับเพิ่มได้" if counts["found"] or counts["unsupported"] else ""
            status.configure(text=" · ".join(parts) + hint)
            if new_found and on_rescan:
                add_btn.pack(side="left")
            again_btn.configure(state="normal")
            send_btn.configure(state="normal")

        def start():
            again_btn.configure(state="disabled")
            send_btn.configure(state="disabled")
            add_btn.pack_forget()
            status.configure(text="กำลังสแกน ~15 วินาที... ขยับเมาส์และกดปุ่มคีย์บอร์ดไว้ระหว่างนี้")
            box = {}

            def work():
                try:
                    box["r"] = on_scan()
                except Exception as exc:
                    box["err"] = exc

            def poll():
                if not top.winfo_exists():
                    return
                if "r" in box:
                    state["entries"] = box["r"][0]
                    render(*box["r"])
                elif "err" in box:
                    status.configure(text=f"สแกนไม่สำเร็จ: {box['err']}")
                    again_btn.configure(state="normal")
                else:
                    top.after(200, poll)
            threading.Thread(target=work, daemon=True).start()
            top.after(200, poll)

        top.bind("<Escape>", lambda _: top.destroy())
        root.update_idletasks()
        top.geometry(f"+{root.winfo_rootx() + root.winfo_width() + 8}+{root.winfo_rooty()}")
        start()

    def show_graph(key, name):
        if graph_win.get("w") is not None and graph_win["w"].winfo_exists():
            graph_win["w"].destroy()
        top = ctk.CTkToplevel(root, fg_color=C["bg"])
        top.title(f"ประวัติแบต — {name}")
        top.resizable(False, False)
        top.attributes("-topmost", True)
        ctk.CTkLabel(top, text=name, font=(TH, 16, "bold"), text_color=C["text"]).pack(anchor="w", padx=18, pady=(14, 0))
        ctk.CTkLabel(top, text="% แบตย้อนหลัง · จุดเหลือง = กำลังชาร์จ", font=(TH, 12),
                     text_color=C["sub"]).pack(anchor="w", padx=18, pady=(0, 8))
        box = ctk.CTkFrame(top, fg_color=C["card"], corner_radius=16, border_width=1, border_color=C["line"])
        box.pack(padx=16, pady=(0, 16))
        draw_graph(box, key).pack(padx=12, pady=12)
        top.bind("<Escape>", lambda _: top.destroy())
        root.update_idletasks()
        top.geometry(f"+{root.winfo_rootx() + root.winfo_width() + 8}+{root.winfo_rooty()}")
        graph_win["w"] = top

    # ---- การ์ดอุปกรณ์ ----
    rows = []
    if not shown:
        empty = ctk.CTkFrame(body, fg_color=C["card"], corner_radius=16)
        empty.pack(fill="x", pady=6)
        ctk.CTkLabel(empty, text="ยังไม่พบอุปกรณ์ที่รองรับ", font=(TH, 15, "bold"),
                     text_color=C["text"]).pack(anchor="w", padx=18, pady=(16, 2))
        ctk.CTkLabel(empty, text="เสียบดองเกิล เปิดอุปกรณ์ แล้วคลิกขวาที่ไอคอน → ค้นหาอุปกรณ์ใหม่",
                     font=(TH, 13), text_color=C["sub"]).pack(anchor="w", padx=18, pady=(0, 16))
    # ponytail: จำนวนการ์ดที่แสดงพร้อมกันประมาณจากความสูงจอ (ส่วนอื่นของหน้าต่าง ~600px, การ์ด ~128px)
    MAX_CARDS = max(1, (work_area_height(root) - 600) // 128)
    devlist = (ctk.CTkScrollableFrame(body, height=MAX_CARDS * 128, fg_color=C["bg"])
               if len(shown) > MAX_CARDS else ctk.CTkFrame(body, fg_color=C["bg"]))
    devlist.pack(fill="x")
    for dev in shown:
        if dev.get("no_battery"):
            connected = dev["connected"]()
            card = ctk.CTkFrame(devlist, fg_color=C["card"], corner_radius=16, border_width=1, border_color=C["line"])
            card.pack(fill="x", pady=4)
            card.grid_columnconfigure(1, weight=1)
            badge = ctk.CTkFrame(card, width=48, height=48, corner_radius=12, fg_color=C["muted"])
            badge.grid(row=0, column=0, rowspan=2, padx=(16, 12), pady=16)
            badge.grid_propagate(False)
            ctk.CTkLabel(badge, text=GLYPH.get(dev.get("kind"), GLYPH[None]), font=("Segoe MDL2 Assets", 20),
                         text_color=C["text"] if connected else C["sub"]).place(relx=0.5, rely=0.5, anchor="center")
            name = ctk.StringVar(value=settings["names"].get(dev["key"], dev["name"]))
            entry = ctk.CTkEntry(card, textvariable=name, font=(TH, 15, "bold"), text_color=C["text"],
                                 fg_color=C["card"], border_width=1, border_color=C["card"], corner_radius=8, height=32)
            entry.grid(row=0, column=1, sticky="ew", pady=(14, 0))
            focus_ring(entry)
            pill = ctk.CTkFrame(card, fg_color=C["muted"], corner_radius=10)
            pill.grid(row=1, column=1, sticky="w", padx=4, pady=(4, 14))
            ctk.CTkLabel(pill, text="● เชื่อมต่ออยู่ · รุ่นนี้ไม่ส่งค่าแบต" if connected else "○ ไม่ได้เสียบดองเกิล",
                         font=(TH, 12), text_color=C["accent"] if connected else C["sub"]).pack(padx=10, pady=1)
            ctk.CTkLabel(card, text="—", font=("Segoe UI", 30, "bold"),
                         text_color=C["sub"]).grid(row=0, column=2, rowspan=2, padx=(8, 16))
            rows.append((dev, None, name))
            continue
        old = last.get(dev["key"])
        stale = bool(dev.get("stale"))
        pct = old[0][0] if old else None
        status, scolor = status_of(old, stale)
        eta = fmt_remaining(estimate_remaining_h((history or {}).get(dev["key"], []), time.time()))
        if eta and old and not stale and not old[0][1]:
            status += f" · เหลือ {eta}"
        color = hexc(level_color(pct)) if pct is not None and not stale else C["sub"]

        card = ctk.CTkFrame(devlist, fg_color=C["card"], corner_radius=16, border_width=1, border_color=C["line"])
        card.pack(fill="x", pady=4)
        card.grid_columnconfigure(1, weight=1)

        badge = ctk.CTkFrame(card, width=48, height=48, corner_radius=12, fg_color=C["muted"])
        badge.grid(row=0, column=0, rowspan=2, padx=(16, 12), pady=(16, 8))
        badge.grid_propagate(False)
        ctk.CTkLabel(badge, text=GLYPH.get(dev.get("kind"), GLYPH[None]), font=("Segoe MDL2 Assets", 20),
                     text_color=color).place(relx=0.5, rely=0.5, anchor="center")

        name = ctk.StringVar(value=settings["names"].get(dev["key"], dev["name"]))
        entry = ctk.CTkEntry(card, textvariable=name, font=(TH, 15, "bold"), text_color=C["text"],
                             fg_color=C["card"], border_width=1, border_color=C["card"], corner_radius=8, height=32)
        entry.grid(row=0, column=1, sticky="ew", pady=(14, 0))
        focus_ring(entry)
        status_row = ctk.CTkFrame(card, fg_color="transparent")
        status_row.grid(row=1, column=1, sticky="ew", padx=4, pady=(4, 0))
        pill = ctk.CTkFrame(status_row, fg_color=C["muted"], corner_radius=10)
        pill.pack(side="left")
        ctk.CTkLabel(pill, text=status, font=(TH, 12), text_color=scolor).pack(padx=10, pady=1)
        hist_btn = ctk.CTkButton(status_row, text="ประวัติ ↗", width=72, height=24, corner_radius=8,
                                 font=(TH, 12), fg_color="transparent", hover_color=C["muted"],
                                 text_color=C["sub"], cursor="hand2")
        hist_btn.pack(side="right")
        hist_btn.configure(command=lambda k=dev["key"], n=name: show_graph(k, n.get().strip() or dev["name"]))

        ctk.CTkLabel(card, text=f"{pct}%" if pct is not None else "--", font=("Segoe UI", 30, "bold"),
                     text_color=color).grid(row=0, column=2, rowspan=2, padx=(8, 16))

        bar = ctk.CTkProgressBar(card, height=8, corner_radius=4, fg_color=C["muted"], progress_color=color)
        bar.set((pct or 0) / 100)
        bar.grid(row=2, column=0, columnspan=2, sticky="ew", padx=(16, 12), pady=(10, 14))

        show = ctk.BooleanVar(value=dev["key"] not in settings["hidden"])
        ctk.CTkSwitch(card, text="แสดงบนแถบงาน", variable=show, font=(TH, 12), text_color=C["sub"],
                      progress_color=C["accent"], button_color=C["text"], fg_color=C["border"],
                      width=40).grid(row=2, column=2, sticky="e", padx=(0, 16), pady=(10, 14))
        rows.append((dev, show, name))

    # ---- ตั้งค่าทั่วไป ----
    ctk.CTkLabel(body, text="การตั้งค่า", font=(TH, 14, "bold"), text_color=C["text"]).pack(anchor="w", pady=(12, 6))
    gen = ctk.CTkFrame(body, fg_color=C["card"], corner_radius=16, border_width=1, border_color=C["line"])
    gen.pack(fill="x")
    gen.grid_columnconfigure(0, weight=1)

    def row_label(r, title, sub):
        f = ctk.CTkFrame(gen, fg_color="transparent")
        f.grid(row=r, column=0, sticky="w", padx=18, pady=8)
        ctk.CTkLabel(f, text=title, font=(TH, 14, "bold"), text_color=C["text"]).pack(anchor="w")
        ctk.CTkLabel(f, text=sub, font=(TH, 12), text_color=C["sub"]).pack(anchor="w")

    def divider(r):
        ctk.CTkFrame(gen, height=1, fg_color=C["line"]).grid(row=r, column=0, columnspan=2, sticky="ew", padx=18)

    def segmented(r, options, current):
        var = ctk.StringVar(value=next((k for k, v in options.items() if v == current), next(iter(options))))
        ctk.CTkSegmentedButton(gen, values=list(options), variable=var, font=(TH, 12), height=32,
                               selected_color=C["accent"], selected_hover_color=C["accent_hover"],
                               unselected_color=C["muted"], unselected_hover_color=C["line"],
                               fg_color=C["muted"], text_color=C["text"]).grid(row=r, column=1, padx=18, sticky="e")
        return var

    intervals = {"30 วิ": 30, "1 นาที": 60, "5 นาที": 300, "15 นาที": 900}
    alerts = {"ปิด": 0, "10%": 10, "20%": 20, "30%": 30}
    row_label(0, "เปิดพร้อม Windows", "เริ่มทำงานเองทุกครั้งที่เปิดเครื่อง")
    startup = ctk.BooleanVar(value=STARTUP_LNK.exists())
    ctk.CTkSwitch(gen, text="", variable=startup, width=40, progress_color=C["accent"], button_color=C["text"],
                  fg_color=C["border"]).grid(row=0, column=1, padx=18, sticky="e")
    divider(1)
    row_label(2, "อัปเดตค่าทุก", "ถี่ขึ้น = เห็นค่าใหม่เร็วขึ้น")
    interval = segmented(2, intervals, settings["interval"])
    divider(3)
    row_label(4, "แจ้งเตือนแบตต่ำ", "เด้งแจ้งเตือนครั้งเดียวเมื่อแบตต่ำกว่าค่านี้")
    alert = segmented(4, alerts, settings["alert"])
    divider(5)
    row_label(6, "แจ้งเตือนชาร์จเต็ม", "สำหรับอุปกรณ์ที่บอกสถานะการชาร์จ")
    notify_full = ctk.BooleanVar(value=settings.get("notify_full", True))
    ctk.CTkSwitch(gen, text="", variable=notify_full, width=40, progress_color=C["accent"], button_color=C["text"],
                  fg_color=C["border"]).grid(row=6, column=1, padx=18, sticky="e")

    if not headsetcontrol_exe():
        hint = ctk.CTkLabel(body, text="ใช้หูฟัง SteelSeries / Corsair / HyperX?  ดาวน์โหลด HeadsetControl ↗",
                            font=(TH, 12), text_color=C["accent"], cursor="hand2")
        hint.pack(anchor="w", pady=(8, 0))
        hint.bind("<Button-1>", lambda _: webbrowser.open(HEADSETCONTROL_URL))

    msg = ctk.CTkLabel(body, text="", font=(TH, 12), text_color=C["danger"])  # pack เมื่อมี error เท่านั้น

    def save(*_):
        switches = [show for _, show, _ in rows if show is not None]
        if switches and not any(v.get() for v in switches):
            msg.configure(text="⚠ ต้องแสดงอย่างน้อย 1 อุปกรณ์ ไม่งั้นจะกลับมาเปิดหน้านี้ไม่ได้")
            msg.pack(anchor="w", pady=(4, 0), before=bar)
            return
        settings["hidden"] = [d["key"] for d, show, _ in rows if show is not None and not show.get()]
        settings["names"] = {d["key"]: n.get().strip() for d, _, n in rows
                             if n.get().strip() and n.get().strip() != d["name"]}
        settings["interval"] = intervals[interval.get()]
        settings["alert"] = alerts[alert.get()]
        settings["notify_full"] = notify_full.get()
        if startup.get() != STARTUP_LNK.exists():
            set_startup(startup.get())
        root.destroy()
        on_save()

    bar = ctk.CTkFrame(body, fg_color="transparent")
    bar.pack(fill="x", pady=(12, 0))
    ctk.CTkButton(bar, text="บันทึก", font=(TH, 14, "bold"), height=42, width=120, corner_radius=10,
                  fg_color=C["accent"], hover_color=C["accent_hover"], text_color=C["on_accent"],
                  cursor="hand2", command=save).pack(side="right")
    ctk.CTkButton(bar, text="ยกเลิก", font=(TH, 14), height=42, width=100, corner_radius=10, fg_color="transparent",
                  border_width=1, border_color=C["border"], hover_color=C["muted"], text_color=C["text"],
                  cursor="hand2", command=root.destroy).pack(side="right", padx=(0, 10))
    root.bind("<Return>", save)
    root.bind("<Escape>", lambda _: root.destroy())

    def center():
        root.update_idletasks()
        w, h = root.winfo_reqwidth(), root.winfo_reqheight()
        root.geometry(f"+{max(0, (root.winfo_screenwidth() - w) // 2)}+{max(0, (work_area_height(root) - h) // 2)}")
    root.after(10, center)
    if open_scan and on_scan:
        root.after(300, show_scan)
    root.mainloop()
