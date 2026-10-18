"""อุปกรณ์ Bluetooth ที่ Windows รู้ค่าแบต"""
import subprocess
from batterytray.config import NO_WINDOW


# ---------- 4. Bluetooth ผ่าน Windows ----------

BT_PROP = "{104EA319-6EE2-4701-BD47-8DDBF425BBE5} 2"


def bt_batteries():
    """{ชื่ออุปกรณ์: %} จาก Windows"""
    ps = ("Get-PnpDevice -PresentOnly -Class Bluetooth,BTHLEDevice -EA 0 | ForEach-Object {"
          f"$b=(Get-PnpDeviceProperty -InstanceId $_.InstanceId -KeyName '{BT_PROP}' -EA 0).Data;"
          "if ($b -ne $null) { \"$($_.FriendlyName)`t$b\" } }")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True,
                             text=True, encoding="utf-8", timeout=60, creationflags=NO_WINDOW).stdout
    except (OSError, subprocess.TimeoutExpired):
        return {}
    res = {}
    for line in out.splitlines():
        name, _, pct = line.rpartition("\t")
        if name and pct.strip().isdigit():
            res[name] = int(pct)
    return res


def bt_devices():
    def read(name):
        v = bt_batteries().get(name)
        return (v, None) if v is not None else None
    return [{"key": "bt:" + n, "kind": None, "name": n, "read": lambda n=n: read(n)} for n in bt_batteries()]
