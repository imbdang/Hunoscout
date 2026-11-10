"""Lịch sử thiết bị ("Lịch sử <tên>"): danh sách sự kiện theo ngày, mới nhất trước, mỗi dòng desc
"<tên> <sự kiện>, HH:MM:SS - DD/MM/YYYY" (4.0.23; 4.0.19: "<tên> <sự kiện>, YYYY-MM-DD HH:MM:SS")."""
from __future__ import annotations

import re
from datetime import datetime

from .. import interact as adb
from ..interact import screen_size
from ..interact import u2 as U2
from .ui import Ui, node

ROW = re.compile(r"(?s)^(.+), (?:(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})|(\d{2}:\d{2}:\d{2}) - (\d{2})/(\d{2})/(\d{4}))$")
MAX_SCROLLS = 20


def _rows(ui: Ui, device: str) -> list[dict]:
    out = []
    for e in ui.elements():
        m = ROW.match(e.desc)
        if m:
            ev = m.group(1).strip()
            if ev.startswith(device.strip()):
                ev = ev[len(device.strip()):].strip()
            out.append({"event": ev, "at": m.group(2) or f"{m.group(6)}-{m.group(5)}-{m.group(4)} {m.group(3)}"})
    return out


def _since(since: str) -> str:
    """'HH:MM[:SS]' (hôm nay theo điện thoại) | 'YYYY-MM-DD HH:MM[:SS]' → 'YYYY-MM-DD HH:MM:SS'."""
    s = since.strip()
    if len(s) <= 8:
        s = adb.adb._shell("date", "'+%Y-%m-%d'").strip() + " " + s
    return datetime.fromisoformat(s).strftime("%Y-%m-%d %H:%M:%S")


def history(scout, device: str, since: str | None = None, wait: float = 4.0) -> list[dict]:
    """→ [{"event": "bật bởi hẹn giờ thường", "at": "2026-11-03 13:23:02"}, …] mới nhất trước (bỏ tên thiết bị ở đầu).
    Không `since` = phần đang thấy. `since` = cuộn xuống tới khi gặp sự kiện cũ hơn mốc → mọi sự kiện từ mốc tới giờ."""
    scout.goto(node(scout, "history/", device))
    ui = Ui(scout)
    ui.find({"descriptionMatches": ROW.pattern}, wait)          # danh sách tải sau khi màn hiện
    rows = _rows(ui, device)
    if not since:
        return rows
    lo = _since(since)
    _, h = screen_size()
    seen = {(r["event"], r["at"]) for r in rows}
    for _ in range(MAX_SCROLLS):
        if not rows or rows[-1]["at"] < lo:
            break
        U2.drag(Ui.SCROLL_X, int(h * 0.75), int(h * 0.35))
        new = [r for r in _rows(ui, device) if (r["event"], r["at"]) not in seen]
        if not new:                                             # cuối danh sách (hoặc đang tải thêm)
            ui.find({"descriptionMatches": ROW.pattern}, 1.0)
            new = [r for r in _rows(ui, device) if (r["event"], r["at"]) not in seen]
            if not new:
                break
        seen.update((r["event"], r["at"]) for r in new)
        rows += new
    scout.nav.scroll.pop(scout.nav.cur, None)                  # đã cuộn tay → navigator không giữ độ cuộn cũ
    return [r for r in rows if r["at"] >= lo]
