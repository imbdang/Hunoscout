"""Backend uiautomator2: server thường trực trên máy → dump ~0.45 s, hỏi phần tử ~0.13 s.

Cùng tên hàm với adb.py. Server được đẩy lên máy và bật ở lần gọi đầu tiên.
Lưu ý: dump_hierarchy() làm hỏng ký tự ngoài BMP (icon MDI U+F0xxx thành ".."), nên tìm
glyph phải hỏi thẳng trên máy bằng find(), không dò trong XML.
"""
from __future__ import annotations

import time
from pathlib import Path

import uiautomator2 as u2

from . import adb

_d = None


def _dev():
    global _d
    if _d is None:
        _d = u2.connect(adb.serial())
    return _d


def reset() -> None:
    """Gọi khi đổi máy."""
    global _d
    _d = None


def _bounds(obj) -> tuple[int, int, int, int]:
    b = obj.info["bounds"]
    return b["left"], b["top"], b["right"], b["bottom"]


# ---- thao tác ----

def tap(x: int, y: int) -> None:
    _dev().click(x, y)


def hold(x: int, y: int, ms: int = 800) -> None:
    _dev().long_click(x, y, ms / 1000)


def swipe(x1: int, y1: int, x2: int, y2: int, ms: int = 300) -> None:
    _dev().swipe(x1, y1, x2, y2, duration=ms / 1000)


def back() -> None:
    _dev().press("back")


def home() -> None:
    _dev().press("home")


# ---- đọc màn ----

def dump(retries: int = 3) -> str:
    return _dev().dump_hierarchy()


def screenshot(path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    _dev().screenshot().save(p)
    return p


def wait(selector: dict, timeout: float) -> tuple[int, int, int, int] | None:
    """Chờ (ngay trên máy) tới khi có phần tử khớp selector → bounds, hết giờ → None."""
    obj = _dev()(**selector)
    return _bounds(obj) if obj.wait(timeout=timeout) else None


def wait_band(selector: dict, band: tuple[int, int], timeout: float, tol: int = 24) -> tuple[int, int, int, int] | None:
    """Như wait() nhưng chỉ nhận phần tử có tâm y trong dải `band` (vị trí title đã học).

    Cùng chữ có thể xuất hiện ở chỗ khác (vd chip tên phòng) — chỉ đúng chỗ title mới tính.
    """
    cy = (band[0] + band[1]) / 2
    ok = lambda b: abs((b[1] + b[3]) / 2 - cy) <= tol
    end = time.monotonic() + timeout
    obj = _dev()(**selector)
    while True:
        left = end - time.monotonic()
        if left <= 0 or not obj.wait(timeout=left):
            return None
        try:
            b = _bounds(obj)                       # phần tử đầu (thường chính là title)
            if ok(b):
                return b
            for i in range(1, obj.count):          # hiếm: chữ trùng nằm trước title trong cây
                b = _bounds(obj[i])
                if ok(b):
                    return b
        except u2.UiObjectNotFoundError:           # phần tử vừa biến mất giữa hai lần hỏi
            pass
        time.sleep(0.05)


def locate(selector: dict) -> tuple[int, int, int, int] | None:
    """Khung của phần tử khớp selector ngay lúc này — một lần hỏi máy, không chờ, không dump."""
    try:
        return _bounds(_dev()(**selector))
    except u2.UiObjectNotFoundError:
        return None


def drag(x: int, y1: int, y2: int, steps: int = 3, hold: float = 0.08) -> None:
    """Kéo dọc bằng chạm thật (down → move → giữ yên → up): không có quán tính, quãng cuộn ổn định.

    Đo trên 2fc3878f: ~0.8 s, kéo 250 px → cuộn 200 px (Android nuốt ~50 px ngưỡng chạm).
    swipe_points chính xác tương đương nhưng mất ~2.5 s; swipe thường còn quán tính.
    """
    t = _dev().touch
    t.down(x, y1)
    for i in range(1, steps + 1):
        t.move(x, y1 + (y2 - y1) * i // steps)
    time.sleep(hold)
    t.up(x, y2)


def find(selector: dict) -> tuple[int, int, int, int] | None:
    """Bounds của phần tử khớp selector ở thời điểm hiện tại, không chờ."""
    obj = _dev()(**selector)
    return _bounds(obj) if obj.exists else None
