"""Backend uiautomator2: server thường trực trên máy (sống qua các lần chạy), 1 kết nối HTTP giữ sống.

Cùng tên hàm với adb.py. Server được đẩy lên máy và bật ở lần gọi đầu tiên.
Lưu ý: dump_hierarchy() làm hỏng ký tự ngoài BMP (icon MDI U+F0xxx thành ".."), nên tìm
glyph phải hỏi thẳng trên máy bằng find(), không dò trong XML.
"""
from __future__ import annotations

import atexit
import json
import subprocess
import time
from pathlib import Path

import requests
import uiautomator2 as u2
from uiautomator2 import core as _core
from uiautomator2.core import BasicUiautomatorServer

from . import adb

_d = None
_rpc = BasicUiautomatorServer.jsonrpc_call

# ---- đường truyền: giữ 1 kết nối HTTP sống ----
# u2 3.x mở kết nối adb MỚI cho mỗi lệnh rồi đóng (adbutils ngủ 10 ms khi đóng): lệnh rỗng ~120 ms.
# adb forward 1 lần + requests.Session (keep-alive): ~66 ms → mỗi RPC bớt ~50 ms (đo 2026-11-03 trên 2fc3878f).
_sessions: dict[tuple[str, int], tuple[int, requests.Session]] = {}


def _http_request(dev, device_port, method, path, data=None, timeout=10.0, print_request=False):
    key = (dev.serial, device_port)
    if key not in _sessions:
        _sessions[key] = (dev.forward_port(device_port), requests.Session())
    local, sess = _sessions[key]
    try:
        r = sess.request(method, f"http://127.0.0.1:{local}{path}", data=json.dumps(data) if data else None,
                         headers={"Content-Type": "application/json", "Accept-Encoding": ""}, timeout=timeout)
    except requests.exceptions.Timeout as e:
        raise _core.HTTPTimeoutError(f"HTTP request timeout: {e}") from e
    except requests.exceptions.ConnectionError as e:   # server chết / chưa chạy → ConnectionError: bật lại server
        _sessions.pop(key, None)
        raise ConnectionError(str(e)) from e
    if r.status_code != 200:
        raise _core.HTTPError(f"HTTP request failed: {r.status_code} {r.reason}")
    return _core.HTTPResponse(r.content)


_core._http_request = _http_request


# ---- server: chạy tách khỏi tiến trình Python, sống qua các lần chạy ----
# u2 bật server bằng adb shell gắn với tiến trình + atexit tắt khi thoát → mỗi lần chạy CLI bật lại server (~1–2 s),
# và lần chạy ngay sau dính server đang chết (RemoteDisconnected). setsid + stdin nối tail -f: thoát vẫn sống.
class _Detached:
    output = b""

    def __init__(self, dev):
        self.dev = dev

    def pool(self):
        return None

    def wait(self):
        return True

    def kill(self):
        """Diệt server + sh bọc + tail theo PID (lọc ở máy tính). KHÔNG dùng pkill -f: dòng lệnh của chính shell chạy
        pkill cũng chứa mẫu → pkill tự giết shell cha, lệnh sau không chạy, wrapper/tail sót lại chặn lần bật sau."""
        pids = [ln.split(None, 1)[0] for ln in self.dev.shell("ps -A -o PID,ARGS").splitlines()[1:]
                if (ln.split(None, 1) + [""])[1].startswith(("app_process / com.wetest.uia2.Main",
                                                              "sh -c tail -f /dev/null | CLASSPATH",
                                                              "tail -f /dev/null"))]
        if pids:
            self.dev.shell("kill -9 " + " ".join(pids))


def _launch_detached(dev, port):
    """Bật server tách rời rồi chờ log "listening". stdin phải còn mở (server thoát khi stdin đóng: đã thử </dev/null,
    nohup đều chết khi adb shell đóng) → nối tail -f. Vừa tắt instance cũ xong bật ngay hay gặp "already registered"
    (UiAutomation cũ chưa nhả) → tắt, đợi 1 s, bật lại."""
    log = "/data/local/tmp/u2.log"
    for _ in range(3):
        # qua adb của hệ thống: adbutils dev.shell(...) thì tiến trình nền chết ngay khi phiên shell đóng (2026-11-04,
        # sau khi adb daemon khởi động lại) — adb CLI thì sống
        subprocess.run(["adb", "-s", dev.serial, "shell",
                        f"setsid sh -c 'tail -f /dev/null | CLASSPATH=/data/local/tmp/u2.jar app_process /"
                        f" com.wetest.uia2.Main -p {port}' >{log} 2>&1 &"], capture_output=True, timeout=15)
        end = time.time() + 8
        while time.time() < end:
            time.sleep(0.3)
            out = dev.shell(f"cat {log}")
            if "listening on" in out:
                return _Detached(dev)
            if "already registered" in out:
                break
        _Detached(dev).kill()
        time.sleep(1.0)
    return _Detached(dev)                         # không lên → _wait_ready của u2 báo "server not ready"


_core.launch_uiautomator = _launch_detached


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
        atexit.unregister(_d.stop_uiautomator)  # không tắt server khi thoát (xem _launch_detached)
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
    """1 RPC click(x, y, 10): server giữ 10 ms. click(x, y) thường = down + ngủ cứng 100 ms + up (u2.jar
    AutomatorServiceImpl) → ~190 ms; down/up riêng = 2 RPC ~137 ms (đo 2026-11-03, đã giữ kết nối sống)."""
    _dev().jsonrpc.click(x, y, 10)


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
    """Phần tử thấp nhất nằm trọn trong [top, bottom] có chữ không trùng phần tử nào khác → (selector, y trên).
    Mốc đo độ cuộn cho lần kéo tới. 1 dump (~0.2 s).

    Bỏ chữ có ".." — dump làm hỏng ký tự icon ngoài BMP (mũi tên › cuối mỗi dòng: desc "Lịch sử, ..") → selector theo
    chữ dump không khớp chữ thật trên máy → mất mốc → coi như cuộn đủ px (đo sai: ghi 1185 px trên trang chỉ 853 px,
    to_top kéo quá đầu → pull-to-refresh → tap lệch). Ưu tiên text của TextView (không dính icon)."""
    from .. import config
    from ..ui_map.element import parse
    els = parse(dump(), config.APP_PACKAGE)
    seen: dict[str, int] = {}
    for e in els:
        for v in (e.desc.strip(), e.text.strip()):
            if v:
                seen[v] = seen.get(v, 0) + 1
    for e in reversed(els):
        b = e.bounds
        if b[1] < top or b[3] > bottom:
            continue
        for key, raw in (("text", e.text), ("description", e.desc)):
            v = raw.strip()
            if v and ".." not in v and seen[v] == 1:
                return {key: raw}, b[1]
    return None


def find(selector: dict) -> tuple[int, int, int, int] | None:
    """Bounds của phần tử khớp selector ở thời điểm hiện tại, không chờ."""
    obj = _dev()(**selector)
    return _bounds(obj) if obj.exists else None
