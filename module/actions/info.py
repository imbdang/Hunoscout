"""Thông tin chung (infoDeviceCommonView): mỗi dòng = nhãn + giá trị (desc "<nhãn>, <giá trị>[, ..]"). Chỉ đọc.
Dòng "Phiên bản phần cứng" = "<phiên bản>\n<trạng thái>" (vd "260331\nMới nhất") — bấm vào là luồng cập nhật
firmware (OTA), CHƯA làm."""
from __future__ import annotations

from .ui import Ui, node


def _glyph(t: str) -> bool:
    return all(0xE000 <= ord(c) <= 0xF8FF or c == "." for c in t)        # icon font / ".." (mũi tên)


def general_info(scout, device: str) -> dict:
    """→ {"fields": {"Nơi sản xuất": "HUNONIC Việt Nam", …}, "firmware": {"version": "260331", "status": "Mới nhất"}}."""
    scout.goto(node(scout, "general_info/", device))
    ui = Ui(scout)
    ui.find(ui.text_sel(key="production"), 3.0)                        # dòng tải sau khi màn hiện
    els = ui.elements()
    texts = [e for e in els if e.text.strip() and not _glyph(e.text.strip()) and e.bounds[1] > 290]
    fields = {}
    for row in (e for e in els if e.desc.strip() and "," in e.desc and e.bounds[1] > 290):
        inside = [t.text.strip() for t in texts if row.bounds[0] <= t.bounds[0] and t.bounds[2] <= row.bounds[2]
                  and row.bounds[1] <= t.bounds[1] and t.bounds[3] <= row.bounds[3]]
        if len(inside) >= 2 and inside[0] not in fields:
            fields[inside[0]] = inside[1]
    hw = next((v for k, v in fields.items() if k in ui.texts("hardwareVersion")), None)
    out = {"fields": fields}
    if hw is not None:
        parts = [p.strip() for p in hw.split("\n") if p.strip()]
        out["firmware"] = {"version": parts[0] if parts else "", "status": " ".join(parts[1:])}
    return out
