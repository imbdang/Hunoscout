"""Backend uiautomator2: server thường trực trên máy → dump ~0.45 s, hỏi phần tử ~0.13 s.

Cùng tên hàm với adb.py. Server được đẩy lên máy và bật ở lần gọi đầu tiên.
Lưu ý: dump_hierarchy() làm hỏng ký tự ngoài BMP (icon MDI U+F0xxx thành ".."), nên tìm
glyph phải hỏi thẳng trên máy bằng find(), không dò trong XML.
"""
from __future__ import annotations

import time
from pathlib import Path

import uiautomator2 as u2
from uiautomator2.core import BasicUiautomatorServer

from . import adb

_d = None
_rpc = BasicUiautomatorServer.jsonrpc_call


def _jsonrpc_call(self, method, params=None, timeout=10):
    """u2 tắt server của tiến trình khi thoát (atexit, không chờ) → tiến trình chạy ngay sau dùng phải server đang
    chết: lệnh đầu qua, lệnh sau RemoteDisconnected (u2 chỉ tự khởi động lại khi HTTPError). Đứt → bật server mới, hỏi lại."""
    try:
        return _rpc(self, method, params, timeout)
    except ConnectionError:
        self.stop_uiautomator()
        self.start_uiautomator()
        return _rpc(self, method, params, timeout)


BasicUiautomatorServer.jsonrpc_call = _jsonrpc_call


def _dev():
    global _d
    if _d is None:
        _d = u2.connect(adb.serial())
        for i in range(3):                       # kết nối mới hay làm server trên máy khởi động lại → lệnh đầu
            try:                                 # dễ RemoteDisconnected; hỏi thử cho tới khi server trả lời
                _d.info
                break
            except Exception:
                if i == 2:
                    raise
                time.sleep(1.0)
    return _d


def reset() -> None:
    """Gọi khi đổi máy."""
    global _d
    _d = None


def _bounds(obj) -> tuple[int, int, int, int] | None:
    """Khung phần tử; None nếu nó vừa biến mất giữa lúc tìm và lúc đọc (màn đang chuyển):
    UiObjectNotFoundError, hoặc StaleObjectException (u2 báo thành RPCUnknownError)."""
    try:
        b = obj.info["bounds"]
    except u2.exceptions.RPCError as err:
        if isinstance(err, u2.UiObjectNotFoundError) or "StaleObjectException" in str(err):
            return None
        raise
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
    end = time.monotonic() + timeout
    obj = _dev()(**selector)
    while (left := end - time.monotonic()) > 0 and obj.wait(timeout=left):
        if b := _bounds(obj):
            return b
        time.sleep(0.05)                           # vừa biến mất → hỏi lại tới hết giờ
    return None


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
        b = _bounds(obj)                           # phần tử đầu (thường chính là title)
        if b and ok(b):
            return b
        for i in range(1, obj.count):              # hiếm: chữ trùng nằm trước title trong cây
            b = _bounds(obj[i])
            if b and ok(b):
                return b
        time.sleep(0.05)


def locate(selector: dict) -> tuple[int, int, int, int] | None:
    """Khung của phần tử khớp selector ngay lúc này — một lần hỏi máy, không chờ, không dump."""
    return _bounds(_dev()(**selector))


NUDGE = 30   # px nhích đầu mỗi lần kéo: vượt ngưỡng chạm, nội dung KHÔNG cuộn đoạn này


def drag(x: int, y1: int, y2: int, hold: float = 0.05) -> None:
    """Kéo dọc bằng chạm thật: down → nhích NUDGE px (qua ngưỡng chạm) → nhảy thẳng tới y2 → đứng yên → up.
    Không quán tính; nội dung cuộn đúng |y2 − y1| − NUDGE.

    Đo trên 2fc3878f (trang chi tiết Module Input): 0.45–0.55 s, kéo 400 → cuộn 370, 700 → 670 (mọi lần như nhau).
    Trước: 3 bước đều nhau → 0.6–0.7 s và mất trọn bước đầu (400 → 266). swipe / swipe_points đều văng.
    Mỗi điểm chạm là 1 RPC (~0.1 s) nên ít điểm = nhanh; khoảng RPC giữa move cuối và up đủ để không thành vuốt.
    """
    t = _dev().touch
    t.down(x, y1)
    t.move(x, y1 - NUDGE if y2 < y1 else y1 + NUDGE)
    t.move(x, y2)
    time.sleep(hold)
    t.up(x, y2)


def lowest(top: int, bottom: int) -> tuple[dict, int] | None:
    """Phần tử bấm được thấp nhất nằm trọn trong [top, bottom] và chỉ có 1 cái như vậy → (selector, y trên).
    Dùng làm mốc đo độ cuộn của lần kéo kế tiếp. Không dump: đếm rồi đọc ngược từ cuối (thứ tự cây = thứ tự dòng)."""
    objs = _dev()(clickable=True)
    n = objs.count
    for i in range(n - 1, max(-1, n - 9), -1):
        try:
            info = objs[i].info
        except Exception:
            continue
        b = info["bounds"]
        if b["top"] < top or b["bottom"] > bottom:
            continue
        desc, text = (info.get("contentDescription") or "").strip(), (info.get("text") or "").strip()
        sel = {"description": info["contentDescription"]} if desc else {"text": info["text"]} if text else None
        if sel and _dev()(**sel).count == 1:
            return sel, b["top"]
    return None


def find(selector: dict) -> tuple[int, int, int, int] | None:
    """Bounds của phần tử khớp selector ở thời điểm hiện tại, không chờ."""
    obj = _dev()(**selector)
    return _bounds(obj) if obj.exists else None
