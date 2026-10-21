"""รวมอุปกรณ์จากทุกแหล่ง"""
from batterytray.config import log_error
from batterytray.devices.bluetooth import bt_devices
from batterytray.devices.compx import compx_devices
from batterytray.devices.headsetcontrol import headset_devices
from batterytray.devices.logitech import logi_devices
from batterytray.devices.nobattery import nobattery_devices
from batterytray.devices.valkyrie import valkyrie_devices


def discover(cache):
    """รวมอุปกรณ์จากทุกแหล่ง — คืนรายการ {key, kind, name, read}"""
    devices = []
    for source in (lambda: compx_devices(cache.setdefault("kinds", {}), cache.setdefault("compx_pages", {})), lambda: logi_devices(cache),
                   valkyrie_devices, headset_devices, bt_devices, lambda: nobattery_devices(cache)):
        try:
            devices += source()
        except Exception:  # แหล่งใดพังไม่ควรทำให้แหล่งอื่นหาย — แต่จดไว้ให้ไล่ปัญหาได้
            log_error("discover")
    return devices
