"""Khoá công tắc (dòng "Khoá công tắc" ở màn chi tiết thiết bị → sheet 4 lựa chọn, chọn là gửi lệnh ngay)."""
from __future__ import annotations

from .ui import ActionError, Ui, arrive, node

MODES = {"device": "lockOnDevice", "app": "lockOnApp", "both": "lockOnDeviceAndApp", "none": "notLocked"}


def _current(ui: Ui) -> str | None:
    desc = ui.d(**ui.row_sel(key="lockSwitch")).info["contentDescription"]
    sub = desc.split(",")[1].strip() if "," in desc else ""
    for mode, key in MODES.items():
        if sub in ui.texts(key):
            return mode
    return None


def get_lock(scout, device: str) -> str | None:
    """Chế độ khoá đang hiện ở dòng "Khoá công tắc": device | app | both | none."""
    scout.goto(node(scout, "infoDevice@", device))
    return _current(Ui(scout))


def set_lock(scout, device: str, mode: str) -> str:
    """Đặt chế độ khoá; chờ dòng "Khoá công tắc" hiện chế độ mới (thiết bị đã nhận lệnh). → chế độ sau khi đặt."""
    if mode not in MODES:
        raise ActionError(f"mode phải là một trong {list(MODES)}")
    info = node(scout, "infoDevice@", device)
    scout.goto(info)
    ui = Ui(scout)
    if _current(ui) == mode:
        return mode
    ui.tap(ui.need(ui.row_sel(key="lockSwitch"), "dòng Khoá công tắc"))
    ui.pick(MODES[mode], what=f"lựa chọn khoá {mode}")
    arrive(scout, info)
    want = ui.texts(MODES[mode])
    if not ui.find(ui.row_sel(texts=[f"{t0}, {t}" for t0 in ui.texts("lockSwitch") for t in want]), 6.0):
        raise ActionError(f"đã chọn {mode} nhưng dòng Khoá công tắc vẫn là {_current(ui)}")
    return mode
