"""Trạng thái bật/tắt của thiết bị: chữ dưới tên ở thẻ đầu màn chi tiết ("Đang bật" = key online, "Đang tắt" = offline)."""
from __future__ import annotations

from .ui import ActionError, Ui, node


def get_power(scout, device: str) -> str:
    """"on" | "off" — đọc thẻ đầu màn chi tiết (trang đang cuộn xuống thì về đầu trang trước)."""
    info = node(scout, "infoDevice@", device)
    scout.goto(info)
    ui = Ui(scout)
    on, off = set(ui.texts("online")), set(ui.texts("offline"))
    for attempt in range(2):
        for e in ui.elements():
            t = e.text.strip()
            if t in on or t in off:
                return "on" if t in on else "off"
        if attempt == 0:
            scout.nav.to_top(info)
            ui = Ui(scout)
    raise ActionError("không thấy chữ Đang bật / Đang tắt ở thẻ đầu màn chi tiết")
