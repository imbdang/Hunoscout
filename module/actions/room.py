"""Phòng của thiết bị: dòng "Phòng" ở màn chi tiết (chữ phụ = phòng hiện tại) → sheet "Chọn phòng" (mọi phòng của
nhà, phòng hiện tại tô xanh, không có nút huỷ). Chọn = gửi POST /v3/device/updateRoot ngay, không hỏi lại; app tự
tải lại danh sách thiết bị (listDeviceOfHomeSelect) và hiện banner "Thành công, Cập nhật thành công" ~3 s đè header
(che ‹; phím Back không bị chặn). Đã thấy trên app 4.0.23.

Thiết bị sang phòng khác → cạnh detailRoom[phòng] → infoDevice đổi → lấy danh sách mới (mitm) rồi dựng lại map.
App vẫn giữ detailRoom[phòng cũ] phía sau màn chi tiết nhưng map mới không còn cạnh đó (Back về đâu không đi được)
→ Back về đó, nhận diện lại, đi vào lại qua phòng mới: 📍 khớp app và kiểm luôn ô thiết bị đã ở phòng mới.
"""
from __future__ import annotations

import time

from .. import config
from .. import interact as adb
from ..parse_data import MitmCapture
from .press import _sub, _wait_sub
from .ui import ActionError, Ui, arrive, node


def get_room(scout, device: str) -> str:
    """Tên phòng đang hiện ở dòng "Phòng" của màn chi tiết."""
    scout.goto(node(scout, "infoDevice@", device))
    return _sub(Ui(scout), "room")


def set_room(scout, device: str, room: str) -> str:
    """Chuyển thiết bị sang phòng `room` (tên phòng trong nhà) → tên phòng dòng "Phòng" hiện sau khi đổi."""
    rooms = [n[len("detailRoom["):-1] for n in scout.graph.nodes if n.startswith("detailRoom[")]
    if room.strip() not in (r.strip() for r in rooms):
        raise ActionError(f"không có phòng {room!r}; nhà có: {rooms}")
    info = node(scout, "infoDevice@", device)
    scout.goto(info)
    ui = Ui(scout)
    if _sub(ui, "room").strip() == room.strip():
        return _sub(ui, "room")
    cap = MitmCapture(config.EXPORTS, config.MITM_FLOWS)
    cap.start()
    ui.tap(ui.need(ui.row_sel(key="room"), "dòng Phòng"))
    ui.need(ui.text_sel(key="selectRoom"), "sheet Chọn phòng")
    ui.settle()
    ui.pick(text=room, what=f"phòng {room!r} trong sheet Chọn phòng")
    arrive(scout, info)
    got = _wait_sub(ui, "room", lambda s: s.strip() == room.strip(), f"đổi sang phòng {room}")
    cap.wait_list(timeout=15)                  # app tự tải lại danh sách sau khi đổi
    scout.reload()
    adb.back()
    ui.last_tap = time.monotonic()
    ui.settle(Ui.SCREEN_MS)                    # màn phòng cũ còn trượt vào → tap ‹ header lúc này bị bỏ qua
    if scout.nav.where() is None:
        raise ActionError("đổi phòng xong, Back từ màn chi tiết thì không nhận ra màn")
    scout.goto(info)
    return got
