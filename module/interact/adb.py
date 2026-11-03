"""Nói chuyện với điện thoại qua adb: thao tác (tap, hold, swipe, ...) và đọc màn (dump, screenshot).

Tầng này chỉ làm việc với toạ độ pixel, không biết gì về màn hình hay node.
"""
from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path

SERIAL: str | None = os.environ.get("ANDROID_SERIAL")  # None = máy duy nhất đang cắm
TIMEOUT = 20  # giây cho mỗi lệnh adb

_REMOTE_XML = "/sdcard/hunoscout_dump.xml"
_size: tuple[int, int] | None = None


class AdbError(RuntimeError):
    """Lệnh adb thất bại hoặc quá thời gian."""


def set_serial(serial: str | None) -> None:
    """Chọn máy khi cắm nhiều máy."""
    global SERIAL, _size
    SERIAL, _size = serial, None


def _run(*args: str, timeout: float = TIMEOUT) -> bytes:
    cmd = ["adb", *(["-s", SERIAL] if SERIAL else []), *args]
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise AdbError(f"quá {timeout}s: {' '.join(cmd)}") from e
    if p.returncode != 0:
        err = p.stderr.decode(errors="replace").strip() or f"exit {p.returncode}"
        raise AdbError(f"{' '.join(cmd)} → {err}")
    return p.stdout


def _shell(*args: object) -> str:
    return _run("shell", *map(str, args)).decode(errors="replace")


# ---- thông tin máy ----

def devices() -> list[str]:
    """Serial các máy đang cắm và sẵn sàng."""
    out = subprocess.run(["adb", "devices"], capture_output=True, text=True, timeout=TIMEOUT).stdout
    return [line.split()[0] for line in out.splitlines()[1:] if line.endswith("\tdevice")]


def serial() -> str:
    """Serial của máy đang dùng (ro.serialno)."""
    return SERIAL or _shell("getprop", "ro.serialno").strip()


def current_package() -> str | None:
    """Package của cửa sổ đang có focus, None nếu không đọc được."""
    m = re.search(r"mCurrentFocus=Window\{[^}]*? ([\w.]+)/", _shell("dumpsys", "window"))
    return m.group(1) if m else None


def launch(package: str) -> None:
    """Mở app như bấm icon ngoài launcher."""
    _shell("monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", 1)


def force_stop(package: str) -> None:
    """Thoát hẳn app (lần mở sau bắt đầu lại từ Home, tải lại danh sách thiết bị)."""
    _shell("am", "force-stop", package)


def device_profile(package: str) -> dict:
    """Hồ sơ máy: định danh + những gì làm toạ độ thay đổi (màn, density, cỡ chữ, bản app)."""
    props = dict(re.findall(r"\[([^\]]+)\]: \[([^\]]*)\]", _shell("getprop")))
    w, h = screen_size()
    density = int(re.findall(r"(\d+)", _shell("wm", "density"))[-1])
    try:
        font_scale = float(_shell("settings", "get", "system", "font_scale").strip())
    except ValueError:  # "null" khi chưa từng đổi cỡ chữ
        font_scale = 1.0
    m = re.search(r"versionName=(\S+)", _shell("dumpsys", "package", package))
    return {
        "serial": props.get("ro.serialno"),
        "model": props.get("ro.product.model"),
        "device": props.get("ro.product.device"),
        "android": props.get("ro.build.version.release"),
        "fingerprint": props.get("ro.build.fingerprint"),
        "screen": {"w": w, "h": h, "density": density, "font_scale": font_scale},
        "app": {"package": package, "version": m.group(1) if m else None},
    }


def screen_size() -> tuple[int, int]:
    """(rộng, cao) của màn theo pixel; ưu tiên Override size nếu có."""
    global _size
    if _size is None:
        # "Physical size: WxH" [+ "Override size: WxH"] → lấy cái cuối
        w, h = map(int, re.findall(r"(\d+)x(\d+)", _shell("wm", "size"))[-1])
        _size = (w, h)
    return _size


# ---- thao tác ----

def tap(x: int, y: int) -> None:
    _shell("input", "tap", x, y)


def hold(x: int, y: int, ms: int = 800) -> None:
    """Nhấn giữ = vuốt tại chỗ trong `ms` mili-giây."""
    _shell("input", "swipe", x, y, x, y, ms)


def swipe(x1: int, y1: int, x2: int, y2: int, ms: int = 300) -> None:
    _shell("input", "swipe", x1, y1, x2, y2, ms)


def scroll(direction: str = "down", ratio: float = 0.5, ms: int = 500) -> None:
    """Cuộn nội dung quanh giữa màn.

    direction: "down" = xem phần bên dưới (ngón tay vuốt lên), "up", "left", "right".
    ratio: quãng vuốt so với chiều cao/rộng màn. `ms` càng lớn càng ít trôi quán tính.
    """
    w, h = screen_size()
    cx, cy = w // 2, h // 2
    dx, dy = int(w * ratio / 2), int(h * ratio / 2)
    match direction:
        case "down":
            swipe(cx, cy + dy, cx, cy - dy, ms)
        case "up":
            swipe(cx, cy - dy, cx, cy + dy, ms)
        case "right":
            swipe(cx + dx, cy, cx - dx, cy, ms)
        case "left":
            swipe(cx - dx, cy, cx + dx, cy, ms)
        case _:
            raise ValueError(f"direction không hợp lệ: {direction!r}")


def back() -> None:
    _shell("input", "keyevent", 4)


def home() -> None:
    _shell("input", "keyevent", 3)


# ---- đọc màn ----

def dump(retries: int = 3) -> str:
    """Cây UI hiện tại dạng XML thô. Thử lại khi màn chưa đứng yên (đang có animation)."""
    last = ""
    for _ in range(retries):
        try:
            out = _shell("uiautomator", "dump", _REMOTE_XML)
        except AdbError as e:
            out = str(e)
        if "dumped to" in out:
            xml = _run("exec-out", "cat", _REMOTE_XML).decode("utf-8")
            _shell("rm", "-f", _REMOTE_XML)          # cây UI có thể chứa dữ liệu nhạy cảm (vd ô mật khẩu)
            return xml
        last = out.strip()
        time.sleep(0.5)
    raise AdbError(f"uiautomator dump thất bại: {last}")


def screenshot(path: str | Path) -> Path:
    """Chụp màn hình, lưu PNG vào `path` trên máy tính."""
    png = _run("exec-out", "screencap", "-p")
    if not png.startswith(b"\x89PNG"):
        raise AdbError("screencap không trả về ảnh PNG")
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(png)
    return p
