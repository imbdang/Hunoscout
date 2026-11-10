"""Nhà của tài khoản + đổi nhà đang chọn trên app.

Đổi nhà: Home → bấm tên nhà ở đầu trang (desc "<tên nhà>, .., , <tỉnh>") → sheet "Quản lý nhà" (houseManagement):
dòng Quản lý nhà, Thêm nhà mới, rồi mỗi nhà một dòng (desc "<tên>, <địa chỉ>", nhà đang chọn có dấu tick) → bấm
dòng nhà = chuyển ngay, không hỏi lại; Home vẽ lại với tên nhà mới. Response listDeviceOfHomeSelect có mọi nhà
(+ phòng) nhưng chỉ nhà đang chọn kèm thiết bị → đổi nhà xong app tải lại danh sách: bắt response đó qua mitm
(MitmCapture, như đổi phòng) rồi dựng map của nhà mới.
"""
from __future__ import annotations

from .. import config
from ..parse_data import MitmCapture, latest_response
from .ui import ActionError, Ui

WAIT_HOME = 10.0     # sheet đóng + Home vẽ lại tên nhà mới (tải phòng / thiết bị của nhà mới)


def houses(scout) -> list[dict]:
    """Nhà của tài khoản (theo danh sách thiết bị đã lấy): id, tên, vai trò (1 chủ / 2 được chia sẻ), số phòng,
    số thiết bị (chỉ nhà đang chọn có, nhà khác = 0); `current` = nhà mà map đang dùng."""
    resp, _ = latest_response(config.EXPORTS)
    return [{"id": str(h["id"]), "name": (h.get("name") or "").strip(), "role": h.get("home_role"),
             "rooms": len(h.get("rooms") or []),
             "devices": sum(len(r.get("devices") or []) for r in h.get("rooms") or []),
             "current": str(h["id"]) == scout.home_id}
            for h in resp["data"]]


def switch_house(scout, house: str) -> dict:
    """Chuyển app sang nhà `house` (tên hoặc id) rồi dựng map của nhà đó. Trả nhà mới + thiết bị trong map."""
    hs = houses(scout)
    want = next((h for h in hs if house.strip() in (h["id"], h["name"])), None)
    if want is None:
        raise ActionError(f"không có nhà {house!r}; có: {[h['name'] for h in hs]}")
    scout.goto("home")
    ui = Ui(scout)
    header = ui.need(ui.row_sel(texts=[h["name"] for h in hs]), "tên nhà ở đầu Home")
    if ui.find(ui.row_sel(texts=[want["name"]])) == header:
        # app đã ở nhà này (chọn lại trong sheet thì app không tải lại danh sách) → chỉ đồng bộ map; thiết bị lấy từ
        # response mới nhất — response đó là của nhà khác (bắt trước khi người dùng tự đổi) thì danh sách rỗng
        if scout.home_id != want["id"]:
            scout.use_house(want["id"], want["name"])
        return _result(scout, want)
    ui.tap(header)
    sheet = ui.text_sel(key="houseManagement")
    ui.need(sheet, "sheet Quản lý nhà")
    ui.settle()
    cap = MitmCapture(config.EXPORTS, config.MITM_FLOWS)
    cap.start()
    ui.tap(ui.need(ui.row_sel(texts=[want["name"]]), f"dòng nhà {want['name']!r} trong sheet"))
    if not ui.gone(sheet, WAIT_HOME) or ui.find(ui.row_sel(texts=[want["name"]]), WAIT_HOME) is None:
        raise ActionError(f"chọn nhà {want['name']!r} xong không thấy Home của nhà đó")
    cap.wait_list(timeout=20)
    scout.use_house(want["id"], want["name"])
    return _result(scout, want)


def _result(scout, want: dict) -> dict:
    return {"house": want["name"], "id": want["id"], "screen": scout.goto("home"),
            "devices": sorted(n[n.rindex("[") + 1:-1].strip() for n in scout.report.leaves),   # màn vào của từng thiết bị
            "warnings": scout.report.warnings}
