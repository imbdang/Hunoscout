"""Chế độ nhấn nhả và Hẹn giờ nhanh: hai hộp thoại mở từ dòng ở màn chi tiết thiết bị, chọn số bằng ô số
(bấm → danh sách chọn native), lưu là gửi lệnh ngay.

Chế độ nhấn nhả  "Tự động đảo trạng thái sau (phút:giây)": ô phút + ô giây, Thoát / Lưu lại. 00:00 = tắt.
Hẹn giờ nhanh    ô "Thời gian (Phút)" (danh sách 2–999) + Sẽ bật / Sẽ tắt (xanh = đang chọn),
                 Thoát | Xoá hẹn giờ (khi đang có) / Lưu hẹn giờ. Dòng hiện "14:45 03-11-2026 sẽ tắt".
Hộp thoại luôn mở ở giá trị mặc định (không hiện giá trị đang đặt) → đọc giá trị từ chữ phụ của dòng.
"""
from __future__ import annotations

import re
import time

from .ui import ActionError, Ui, arrive, node


def _sub(ui: Ui, key: str) -> str:
    """Chữ phụ của dòng ở màn chi tiết: "Chế độ nhấn nhả, Tắt, .." → "Tắt"."""
    desc = ui.d(**ui.row_sel(key=key)).info["contentDescription"]
    rest = [p.strip() for p in desc.split(",")[1:] if p.strip() != ".."]
    return rest[0] if rest else ""


def _wait_sub(ui: Ui, key: str, ok, what: str, timeout: float = 6.0) -> str:
    end = time.monotonic() + timeout
    while True:
        sub = _sub(ui, key)
        if ok(sub):
            return sub
        if time.monotonic() > end:
            raise ActionError(f"{what}: dòng vẫn hiện {sub!r}")
        time.sleep(0.3)


def _numbers(ui: Ui) -> list[tuple[int, tuple[int, int, int, int]]]:
    """Ô số trong hộp thoại (desc là số, bấm được), trái → phải."""
    return sorted(((int(e.desc), e.bounds) for e in ui.elements() if e.clickable and e.desc.strip().isdigit()),
                  key=lambda x: x[1][0])


def _set_numbers(ui: Ui, targets: list[int], titles: list[str]) -> None:
    for i, (target, title) in enumerate(zip(targets, titles)):
        nums = _numbers(ui)
        if len(nums) != len(targets):
            raise ActionError(f"thấy {len(nums)} ô số trong hộp thoại, cần {len(targets)}")
        if nums[i][0] != target:
            ui.tap(nums[i][1])
            ui.pick_number(target, title)
    got = [v for v, _ in _numbers(ui)]
    if got != targets:
        raise ActionError(f"đặt {targets} nhưng hộp thoại hiện {got}")


def _cap(texts: list[str]) -> list[str]:
    return [t[:1].upper() + t[1:] for t in texts]


# ---- chế độ nhấn nhả ----

# chữ phụ khi đang bật: "%{name} được tự động %{status1} sau %{minute} phút %{second} giây khi %{status2}"
# (clickModeLAN: chỉ giây; …HasMinuteX60: "%{minute} giờ" = số giờ). Tên thiết bị có thể chứa số → khớp theo mẫu.
PRESS_SUB = {"clickModeLAN": 1, "clickModeLANHasMinute": 1, "clickModeLANHasMinuteX60": 60}


def _template_rx(tpl: str) -> re.Pattern:
    parts = re.split(r"(%\{\w+\})", tpl)
    rx = "".join(f"(?P<{p[2:-1]}>\\d+)" if p in ("%{minute}", "%{second}") else ".*?" if p.startswith("%{")
                 else re.escape(p) for p in parts)
    return re.compile(rf"(?s)^{rx}$")


def _press_value(ui: Ui, sub: str) -> str:
    if sub in ui.texts(["turnOff", "off"]):
        return "00:00"
    for key, mul in PRESS_SUB.items():
        for tpl in ui.texts(key):
            m = _template_rx(tpl).match(sub)
            if m:
                total = int(m.groupdict().get("minute") or 0) * 60 * mul + int(m.groupdict().get("second") or 0)
                return f"{total // 60:02d}:{total % 60:02d}"
    raise ActionError(f"không hiểu chữ phụ Chế độ nhấn nhả {sub!r}")


def get_press_mode(scout, device: str) -> str:
    """Thời gian tự đảo trạng thái "MM:SS" ("00:00" = tắt chế độ nhấn nhả)."""
    scout.goto(node(scout, "infoDevice@", device))
    ui = Ui(scout)
    return _press_value(ui, _sub(ui, "pressMode"))


def set_press_mode(scout, device: str, value: str) -> str:
    """Đặt chế độ nhấn nhả "MM:SS" (giây 0–59; "00:00" = tắt) → giá trị dòng hiện sau khi lưu."""
    m, s = map(int, value.split(":"))
    if not 0 <= s <= 59 or m < 0:
        raise ActionError("value phải là MM:SS, giây 0–59")
    value = f"{m:02d}:{s:02d}"
    info = node(scout, "infoDevice@", device)
    scout.goto(info)
    ui = Ui(scout)
    if _press_value(ui, _sub(ui, "pressMode")) == value:
        return value
    title = ui.text_sel(key="autoClickMode")
    ui.tap(ui.need(ui.row_sel(key="pressMode"), "dòng Chế độ nhấn nhả"))
    ui.need(title, "hộp thoại Chế độ nhấn nhả")
    _set_numbers(ui, [m, s], ["phút", "giây"])
    ui.tap(ui.need(ui.option_sel(key="save"), "nút Lưu lại"))
    if not ui.gone(title, 4.0):
        raise ActionError("bấm Lưu lại nhưng hộp thoại Chế độ nhấn nhả không đóng")
    arrive(scout, info)
    _wait_sub(ui, "pressMode", lambda sub: _press_value(ui, sub) == value, f"đặt nhấn nhả {value}")
    return value


# ---- hẹn giờ nhanh ----

def _quick_value(ui: Ui, sub: str) -> dict | None:
    if not sub or sub in ui.texts("actionTimerEmpty"):
        return None
    m = re.match(r"^(\d{1,2}:\d{2} \d{2}-\d{2}-\d{4})\s+(.+)$", sub)
    if not m:
        raise ActionError(f"không hiểu chữ phụ Hẹn giờ nhanh {sub!r}")
    action = "on" if m.group(2) in ui.texts("willOn") else "off" if m.group(2) in ui.texts("willOff") else m.group(2)
    return {"at": m.group(1), "action": action}


def get_quick_timer(scout, device: str) -> dict | None:
    """Hẹn giờ nhanh đang đặt: {"at": "HH:MM DD-MM-YYYY", "action": "on"|"off"} hoặc None."""
    scout.goto(node(scout, "infoDevice@", device))
    ui = Ui(scout)
    return _quick_value(ui, _sub(ui, "quickTimer"))


def _open_quick(ui: Ui) -> dict:
    save = ui.option_sel(key="saveAlarm")
    ui.tap(ui.need(ui.row_sel(key="quickTimer"), "dòng Hẹn giờ nhanh"))
    ui.need(save, "hộp thoại Hẹn giờ nhanh")
    return save


def set_quick_timer(scout, device: str, minutes: int, action: str = "on") -> dict:
    """Đặt hẹn giờ nhanh: sau `minutes` phút (2–999) sẽ bật/tắt (action "on"|"off"). Đang có thì ghi đè."""
    if action not in ("on", "off"):
        raise ActionError("action phải là on | off")
    info = node(scout, "infoDevice@", device)
    scout.goto(info)
    ui = Ui(scout)
    before = _sub(ui, "quickTimer")
    save = _open_quick(ui)
    _set_numbers(ui, [minutes], ["phút"])
    chips = [ui.need(ui.option_sel(texts=_cap(ui.texts(k))), f"nút {k}") for k in ("willOn", "willOff")]
    want = chips[0] if action == "on" else chips[1]
    if not ui.green([want])[0]:
        ui.tap(want)
        time.sleep(0.3)
    if ui.green(chips) != [action == "on", action == "off"]:
        raise ActionError(f"chọn hành động {action} nhưng nút không đổi màu")
    ui.tap(ui.need(save, "nút Lưu hẹn giờ"))
    if not ui.gone(save, 4.0):
        raise ActionError("bấm Lưu hẹn giờ nhưng hộp thoại không đóng")
    arrive(scout, info)
    sub = _wait_sub(ui, "quickTimer", lambda s: s != before and (_quick_value(ui, s) or {}).get("action") == action,
                    f"đặt hẹn giờ nhanh {minutes} phút {action}")
    return _quick_value(ui, sub)


def delete_quick_timer(scout, device: str) -> bool:
    """Xoá hẹn giờ nhanh đang đặt (không hỏi lại). → False nếu không có gì để xoá."""
    info = node(scout, "infoDevice@", device)
    scout.goto(info)
    ui = Ui(scout)
    if _quick_value(ui, _sub(ui, "quickTimer")) is None:
        return False
    save = _open_quick(ui)
    ui.tap(ui.need(ui.option_sel(key="deleteAlarm"), "nút Xoá hẹn giờ"))
    if not ui.gone(save, 4.0):
        raise ActionError("bấm Xoá hẹn giờ nhưng hộp thoại không đóng")
    arrive(scout, info)
    _wait_sub(ui, "quickTimer", lambda s: _quick_value(ui, s) is None, "xoá hẹn giờ nhanh")
    return True
