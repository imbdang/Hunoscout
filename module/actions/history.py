"""Lịch sử thiết bị ("Lịch sử <tên>"): danh sách sự kiện theo ngày, mới nhất trước, mỗi dòng
desc "<tên> <sự kiện>, YYYY-MM-DD HH:MM:SS". Chỉ đọc phần đang thấy trên màn (chưa cuộn)."""
from __future__ import annotations

import re

from .ui import Ui, node

ROW = re.compile(r"(?s)^(.+), (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})$")


def history(scout, device: str, wait: float = 4.0) -> list[dict]:
    """→ [{"event": "bật bởi hẹn giờ thường", "at": "2026-11-03 13:23:02"}, …] (bỏ tên thiết bị ở đầu)."""
    scout.goto(node(scout, "history/", device))
    ui = Ui(scout)
    ui.find({"descriptionMatches": ROW.pattern}, wait)          # danh sách tải sau khi màn hiện
    out = []
    for e in ui.elements():
        m = ROW.match(e.desc)
        if m:
            ev = m.group(1).strip()
            if ev.startswith(device.strip()):
                ev = ev[len(device.strip()):].strip()
            out.append({"event": ev, "at": m.group(2)})
    return out
