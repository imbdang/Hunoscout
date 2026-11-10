"""Trạng thái bật/tắt của thiết bị: chữ dưới tên ở thẻ đầu màn chi tiết ("Đang bật" = key online, "Đang tắt" = offline)."""
from __future__ import annotations

import time

from .ui import ActionError, Ui, node


def get_power(scout, device: str) -> str:
    """"on" | "off" — đọc thẻ đầu màn chi tiết (trang đang cuộn xuống thì về đầu trang trước)."""
    info = node(scout, "infoDevice@", device)
    scout.goto(info)
    ui = Ui(scout)
    on, off = set(ui.texts("online")), set(ui.texts("offline"))
    for attempt in range(2):
        # chỉ chữ ngay dưới tên thiết bị ở thẻ đầu: dòng "Thông báo khi thiết bị mất kết nối" cũng có chữ phụ
        # "Đang tắt" → trang đang cuộn (thẻ đầu khuất) mà lấy chữ đầu tiên khớp thì đọc ra "off" sai
        els = ui.elements()
        for n in (e for e in els if e.text.strip() == device.strip()):
            for e in els:
                t = e.text.strip()
                if (t in on or t in off) and 0 <= e.bounds[1] - n.bounds[3] < 120 and abs(e.bounds[0] - n.bounds[0]) < 40:
                    return "on" if t in on else "off"
        if attempt == 0:
            scout.nav.to_top(info)
            ui = Ui(scout)
    raise ActionError("không thấy chữ Đang bật / Đang tắt ở thẻ đầu màn chi tiết")


SET_WAIT = 8.0       # đo 2fc3878f: chữ đổi sau 0.7–1.1 s (lệnh đi MQTT, không có HTTP)


def set_power(scout, device: str, state: str) -> dict:
    """Bấm công tắc ở thẻ đầu màn chi tiết cho tới trạng thái `state` (on/off). Đã đúng thì không bấm. App hỏi xác
    nhận (khoá trên ứng dụng) → trả `dialog` (chữ hộp thoại), KHÔNG bấm gì thêm — agent tự chọn HUỶ / ĐỒNG Ý."""
    before = get_power(scout, device)
    if before == state:
        return {"before": before, "after": before, "tapped": False}
    ui = Ui(scout)
    b = ui.need({"className": "android.widget.Switch"}, "công tắc ở thẻ đầu màn chi tiết")
    ui.tap(b)
    t0 = time.monotonic()
    confirm = ui.text_sel(key="textConfirm")
    while time.monotonic() - t0 < SET_WAIT:
        if ui.find(confirm):
            return {"before": before, "after": None, "tapped": True,
                    "dialog": [(e.text or "").strip() for e in ui.elements() if (e.text or "").strip()][:8]}
        now = get_power(scout, device)
        if now == state:
            return {"before": before, "after": now, "tapped": True}
        time.sleep(0.3)
    raise ActionError(f"bấm công tắc nhưng sau {SET_WAIT:.0f} s vẫn chưa thấy trạng thái {state}")
