# Battery Tray

แสดง % แบตเตอรี่ของเมาส์ / คีย์บอร์ด / หูฟังไร้สาย เป็นไอคอนข้างนาฬิกาบน Windows

![tray](docs/tray.png)

- ตัวเลขใหญ่ = % แบต, แถบล่าง = ระดับแบต (เขียว / ส้ม ≤40% / แดง ≤20%)
- สายฟ้าสีเหลือง = กำลังชาร์จ · ตัวเลขสีเทา = ค่าล่าสุด (อุปกรณ์หลับอยู่)
- แจ้งเตือนเมื่อแบตต่ำ
- ดับเบิลคลิกไอคอน = หน้าตั้งค่า · คลิกขวา = รีเฟรช, ค้นหาอุปกรณ์ใหม่, ปิด

## ติดตั้ง (ง่ายสุด — ไม่ต้องมี Python)

1. ดาวน์โหลด **BatteryTray.exe** จากหน้า [Releases](../../releases/latest)
2. วางไว้ในโฟลเดอร์ที่ไม่ลบทิ้ง (เช่น `Documents\BatteryTray`) แล้วดับเบิลคลิก
3. หน้าตั้งค่าจะเปิดขึ้นเอง — เปิดสวิตช์ **เปิดพร้อม Windows** แล้วกดบันทึก

Windows SmartScreen อาจเตือนเพราะไฟล์ไม่มีลายเซ็น — กด *More info → Run anyway*

ถ้าไอคอนไปอยู่ใต้ลูกศร `^` ให้ลากออกมาวางบน taskbar หรือเปิด
Settings → Personalization → Taskbar → Other system tray icons → เปิด **BatteryTray**

### ติดตั้งจากซอร์ส

ติดตั้ง [Python 3](https://www.python.org/downloads/) → ดาวน์โหลด repo → ดับเบิลคลิก `Install.bat`
(เลิกใช้: `Uninstall.bat`, สร้าง exe เอง: `build.bat`)

## หน้าตั้งค่า

- เปิด/ปิดไอคอนของแต่ละอุปกรณ์ และตั้งชื่อเรียกเอง
- เปิดพร้อม Windows
- อัปเดตค่าทุก 30 วินาที / 1 / 5 / 15 นาที
- แจ้งเตือนเมื่อแบต ≤ 10% / 20% / 30% หรือปิดแจ้งเตือน

## อุปกรณ์ที่รองรับ

| ยี่ห้อ / ชนิด | วิธีอ่าน | สถานะ |
|---|---|---|
| เมาส์ดองเกิล 2.4G Compx/ATK (VID `3554`) — VXE, ATK ฯลฯ | โปรโตคอลที่ ATK HUB ใช้ (ถอดจาก USB capture) | ✅ ทดสอบกับ VXE R1 |
| คีย์บอร์ดดองเกิล Compx (VID `3554`) — AULA ฯลฯ | โปรโตคอล AULA จาก [womier-l65-linux](https://github.com/deepan-alve/womier-l65-linux) | ✅ ทดสอบกับ Aula |
| **Logitech** เมาส์ / คีย์บอร์ด / หูฟัง — Unifying, Bolt, Lightspeed, สาย | HID++ 2.0 (feature 0x1004 / 0x1000 / 0x1001) | 🧪 ยังไม่ได้ทดสอบกับของจริง |
| **หูฟัง SteelSeries, Corsair, HyperX, Logitech, Roccat ฯลฯ** | [HeadsetControl](https://github.com/Sapd/HeadsetControl) — วาง `headsetcontrol.exe` ไว้ข้างโปรแกรม | 🧪 ยังไม่ได้ทดสอบกับของจริง |
| อุปกรณ์ **Bluetooth** ทุกยี่ห้อที่ Windows รู้ค่าแบต | `DEVPKEY_Bluetooth_Battery` ของ Windows | 🧪 ยังไม่ได้ทดสอบกับของจริง |

รายชื่อหูฟังที่ HeadsetControl รองรับ: [ดูที่นี่](https://github.com/Sapd/HeadsetControl#supported-headsets)

**ยังไม่รองรับ:** Razer, อุปกรณ์ที่ดองเกิลไม่ส่งค่าแบตมาให้คอม (เช่น หูฟัง SIGNO WP-601 `040b:0897`)

ใช้แล้วเจอปัญหา หรือใช้ได้กับรุ่นไหน — แจ้งใน [Issues](../../issues) ได้เลย

### เพิ่มยี่ห้อใหม่

1. ติดตั้ง Wireshark + USBPcap
2. อัด USB ตอนโปรแกรมของยี่ห้อนั้นกำลังแสดง % แบต
3. หาคำสั่งที่ส่งออก (`URB_CONTROL out` / SET_REPORT) และคำตอบที่มีตัวเลขตรงกับ % ที่โปรแกรมแสดง
4. เพิ่มฟังก์ชัน `*_devices()` ที่คืน `{key, kind, name, read}` แล้วใส่ใน `discover()` ของ `battery_monitor.py`

## ทดสอบ

```
py battery_monitor.py --test
```

ตรวจเฟรมของทุกโปรโตคอลกับคำตอบจริง/จำลอง แล้วพิมพ์ค่าแบตของอุปกรณ์ที่เสียบอยู่

## License

MIT
