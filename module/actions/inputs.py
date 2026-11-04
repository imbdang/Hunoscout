"""Đầu vào của Module Input (swinputv2) ở màn chi tiết thiết bị — các dòng cuối trang (cuộn bằng Ui.reach):

  Cài đặt đầu vào AC          dòng không bấm được + công tắc bên phải (desc Bật/Tắt = trạng thái) — bấm = gửi lệnh
  Cài đặt đầu vào DC (Xanh)   bấm → sheet "Chọn hành động": Bật / Tắt / Không làm gì — chọn = gửi lệnh
  Cài đặt đầu vào DC (Đỏ)     như trên
Chữ dòng ghép: inputText + " AC" / " DC (" + colorGreen|colorRed + ")".
"""
from __future__ import annotations

import time

from ..interact import u2 as U2
from .ui import ActionError, Ui, _rx, arrive, node

DC_ACTION = {"on": "turnOn", "off": "turnOff", "none": "ATM.actionNone"}
COLOR = {"green": "colorGreen", "red": "colorRed"}


def _ac_label(ui: Ui) -> dict:
    return {"textMatches": _rx([f"{t} AC" for t in ui.texts("inputText")])}


def _dc_row(ui: Ui, color: str) -> dict:
    if color not in COLOR:
        raise ActionError(f"color phải là {list(COLOR)}")
    return ui.row_sel(texts=[f"{t} DC ({c})" for t in ui.texts("inputText") for c in ui.texts(COLOR[color])])


def _ac_switch(ui: Ui):
    """→ (phần tử công tắc AC, đang bật?). Công tắc nằm cùng hàng với chữ 'Cài đặt đầu vào AC'."""
    lb = ui.reach(_ac_label(ui), "dòng Cài đặt đầu vào AC")
    cy, on, off = (lb[1] + lb[3]) // 2, set(ui.texts("turnOn")), set(ui.texts("turnOff"))
    sw = next((e for e in ui.elements() if e.clickable and e.desc.strip() in on | off
               and abs((e.bounds[1] + e.bounds[3]) // 2 - cy) < 90), None)
    if sw is None:
        raise ActionError("không thấy công tắc của dòng Cài đặt đầu vào AC")
    return sw, sw.desc.strip() in on


def _dc_value(ui: Ui, sel: dict) -> str | None:
    """Hành động đang đặt của dòng DC; None nếu dòng chưa đọc được (sheet chọn còn đang trượt xuống che trang)."""
    try:
        desc = ui.d(**sel).info["contentDescription"]
    except U2.u2.exceptions.UiObjectNotFoundError:
        return None
    sub = next((p.strip() for p in desc.split(",")[1:] if p.strip() != ".."), "")
    for name, key in DC_ACTION.items():
        if sub in ui.texts(key):
            return name
    raise ActionError(f"không hiểu hành động đầu vào DC {sub!r}")


def get_inputs(scout, device: str) -> dict:
    """{"ac": True|False, "dc_green": "on"|"off"|"none", "dc_red": …} — đọc chữ/desc ở màn chi tiết."""
    scout.goto(node(scout, "infoDevice@", device))
    ui = Ui(scout)
    out = {"ac": _ac_switch(ui)[1]}
    for color in COLOR:
        sel = _dc_row(ui, color)
        ui.reach(sel, f"dòng đầu vào DC {color}")
        out[f"dc_{color}"] = _dc_value(ui, sel)
    return out


def set_input_ac(scout, device: str, on: bool) -> bool:
    """Bật/tắt chế độ đầu vào AC; chờ công tắc đổi desc (thiết bị nhận lệnh). → trạng thái sau khi đặt."""
    scout.goto(node(scout, "infoDevice@", device))
    ui = Ui(scout)
    sw, cur = _ac_switch(ui)
    if cur == on:
        return on
    ui.tap(sw.bounds)
    want = ui.texts("turnOn" if on else "turnOff")
    end = time.monotonic() + 6.0
    while time.monotonic() < end:
        time.sleep(0.3)
        b = U2.locate({"descriptionMatches": _rx(want), "clickable": True})
        if b and abs((b[1] + b[3]) // 2 - (sw.bounds[1] + sw.bounds[3]) // 2) < 30:
            return on
    raise ActionError(f"bấm công tắc đầu vào AC nhưng vẫn {'tắt' if on else 'bật'}")


def set_input_dc(scout, device: str, color: str, action: str) -> str:
    """Đặt hành động khi đầu vào DC xanh/đỏ kích hoạt: on | off | none. → hành động dòng hiện sau khi đặt."""
    if action not in DC_ACTION:
        raise ActionError(f"action phải là {list(DC_ACTION)}")
    info = node(scout, "infoDevice@", device)
    scout.goto(info)
    ui = Ui(scout)
    sel = _dc_row(ui, color)
    b = ui.reach(sel, f"dòng đầu vào DC {color}")
    if _dc_value(ui, sel) == action:                  # đã đúng → không mở sheet, không gửi lệnh
        return action
    ui.tap(b)
    ui.pick(DC_ACTION[action], what=f"hành động {action}")
    arrive(scout, info)
    end = time.monotonic() + 6.0
    while _dc_value(ui, sel) != action:
        if time.monotonic() > end:
            raise ActionError(f"chọn {action} nhưng dòng đầu vào DC {color} vẫn là {_dc_value(ui, sel)}")
        time.sleep(0.3)
    return action
