"""Thao tác và đọc màn hình điện thoại.

Backend: uiautomator2 nếu đã cài (nhanh, chờ phần tử ngay trên máy), không thì lệnh shell adb.
Thông tin máy (serial, profile, app đang mở) luôn đi qua adb shell.
"""
from . import adb
from .adb import (
    AdbError,
    current_package,
    device_profile,
    devices,
    force_stop,
    launch,
    screen_size,
    scroll,
    serial,
)

try:
    from . import u2 as _fast
except ImportError:          # chưa cài uiautomator2
    _fast = None

if _fast is not None:
    from .u2 import back, drag, dump, find, hold, home, locate, screenshot, swipe, tap, wait, wait_band
    BACKEND = "uiautomator2"
else:
    from .adb import back, dump, hold, home, screenshot, swipe, tap
    find = wait = wait_band = locate = drag = None   # Navigator tự rơi về cách dump + so anchors
    BACKEND = "adb"


def set_serial(s: str | None) -> None:
    adb.set_serial(s)
    if _fast is not None:
        _fast.reset()
