"""Cấu hình thiết bị mới qua BLE: Home → nút + → Thêm thiết bị (config.list) → ô ở 'Thiết bị có sẵn xung quanh'.

Đi tay 2026-11-05 trên 2fc3878f, app 4.0.23, Ổ cắm SK01 V2 (sswitch2v) vừa xoá (xoá xong thiết bị tự vào cấu hình):
- config.list tự quét BLE ~10 s mỗi lượt; quét xong hiện "Thử lại" (config.tryAgain), bấm = lượt mới (danh sách làm
  lại, thứ tự ô đổi). Lượt quét có lúc sót thiết bị → bấm lại. Ô = tên mặc định của loại, có thể trùng tên.
- Bấm ô → "Cấu hình qua bluetooth": thiết bị quét wifi rồi trả danh sách (~5 s) → bấm dòng wifi → form "Nhập thông
  tin wifi" (EditText 0 = tên, 1 = mật khẩu) → Xác nhận → "Đang thực hiện cấu hình thiết bị..." (~4 s).
- Thiết bị từng có cấu hình → "PHƯƠNG THỨC CẤU HÌNH": như thiết bị mới / khôi phục cũ → Tiếp theo (API addRoot).
- Màn cuối: tên mặc định (vd "Ổ cắm 3") + công tắc Tắt/Bật cùng hàng, phòng "Chưa xếp phòng" → Hoàn thành (updateRoot,
  setDeviceSuggest) → Home, app tải lại danh sách thiết bị → bắt qua mitm rồi dựng lại map.
NeoR6 (scenario_sw6, 2026-11-05): ô "Công tắc ngữ cảnh" → "Chọn loại cấu hình" (qua bộ trung tâm / Cấu hình trực tiếp)
  → Tiếp theo → ~1,3 s addRoot + updateDataExtra → màn cuối "Tìm thông minh" (tên = ô nhập, phòng = sheet "Chọn phòng").
  BLE mất lúc "Đang lưu lên máy chủ" → ~150 s → "Lỗi cấu hình" (TIMEOUT). updateRoot trả status:false → app không báo,
  đứng ở màn cuối → action báo lỗi kèm lời server.
Mật khẩu wifi chỉ điền lên máy, không ghi đâu cả.
"""
from __future__ import annotations

import json
import time

from .. import config
from ..interact import screen_size
from ..interact import u2 as U2
from ..parse_data import MitmCapture
from ..ui_map.element import parse
from .ui import ActionError, Ui

SCAN_WAIT = 20.0      # một lượt quét BLE ~10 s
WIFI_WAIT = 20.0      # thiết bị quét wifi rồi trả danh sách ~5 s
CONFIG_WAIT = 180.0   # Xác nhận / Tiếp theo → màn phương thức / màn cuối ~1–4 s; BLE mất → 'Lỗi cấu hình' sau ~150 s
DONE_WAIT = 10.0     # Hoàn thành → rời màn cuối
MAX_DRAGS = 6


def _drag(down: bool) -> None:
    _, h = screen_size()
    y1, y2 = (int(h * 0.75), int(h * 0.35)) if down else (int(h * 0.35), int(h * 0.75))
    U2.drag(Ui.SCROLL_X, y1, y2)


def _to_top(ui: Ui) -> None:
    """Kéo lên tới khi thấy tiêu đề 'Thiết bị có sẵn xung quanh'."""
    head = ui.text_sel(key="deviceAvailableAroundText")
    for _ in range(MAX_DRAGS):
        if ui.find(head):
            return
        _drag(down=False)
    ui.need(head, "tiêu đề Thiết bị có sẵn xung quanh")


def _tiles(ui: Ui) -> tuple[list[tuple[str, tuple]], bool]:
    """Ô đang thấy của mục xung quanh: [(tên, bounds)], và đã thấy hết mục chưa (thấy tiêu đề 'Thêm thủ công')."""
    els = parse(U2.dump(), config.APP_PACKAGE)
    title, around, manual = ui.texts("addDevice"), ui.texts("deviceAvailableAroundText"), ui.texts("addManually")
    top = max([e.bounds[3] for e in els if e.text.strip() in title + around], default=0)
    end = [e.bounds[1] for e in els if e.text.strip() in manual]
    bottom = min(end, default=10 ** 9)
    tiles = [(e.desc.strip(), e.bounds) for e in els
             if e.clickable and e.desc.strip() and e.bounds[1] > top and e.bounds[3] < bottom]
    return tiles, bool(end)


def nearby(scout, want: str | None = None, rounds: int = 3) -> dict:
    """Tên thiết bị trong 'Thiết bị có sẵn xung quanh'. `want` chưa có → bấm Thử lại, tối đa `rounds` lượt quét.
    Có `want`: đọc ô ngay trong lúc quét, thấy là trả luôn (ô hiện sau ~1–2 s, cả lượt ~10 s)."""
    scout.goto("config.list")
    ui = Ui(scout)
    retry = ui.text_sel(key="config.tryAgain")
    for i in range(1, rounds + 1):
        _to_top(ui)
        end = time.monotonic() + SCAN_WAIT
        while want and not ui.find(retry):          # đang quét
            if want.strip() in {n for n, _ in _tiles(ui)[0]}:
                return {"devices": [want.strip()], "found": True, "rounds": i, "partial": True}
            if time.monotonic() > end:
                break
            time.sleep(0.3)
        ui.need(retry, "nút Thử lại (lượt quét chưa xong)", max(0.0, end - time.monotonic()))
        names: set[str] = set()
        for _ in range(MAX_DRAGS):
            tiles, last = _tiles(ui)
            names |= {n for n, _ in tiles}
            if last:
                break
            _drag(down=True)
        found = want is not None and want.strip() in names
        if want is None or found or i == rounds:
            return {"devices": sorted(names), "found": found if want is not None else None, "rounds": i}
        _to_top(ui)
        ui.tap(ui.need(retry, "nút Thử lại"))
        ui.gone(retry, 3)                        # đang quét: nút ẩn


def _tile(ui: Ui, device: str) -> tuple:
    _to_top(ui)
    for _ in range(MAX_DRAGS):
        tiles, last = _tiles(ui)
        hits = [b for n, b in tiles if n == device.strip()]
        if len(hits) > 1:
            raise ActionError(f"có {len(hits)} ô {device!r} xung quanh — không biết ô nào là thiết bị cần cấu hình")
        if hits:
            return hits[0]
        if last:
            break
        _drag(down=True)
    raise ActionError(f"không thấy ô {device!r} (danh sách quét đã đổi?)")


def _first(ui: Ui, sels: list[dict], timeout: float) -> int | None:
    """Chờ tới khi một trong các selector hiện → chỉ số của nó."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        for i, s in enumerate(sels):
            if U2.locate(s):
                return i
        time.sleep(0.3)
    return None


def _wifi_row(ui: Ui, wifi: str) -> tuple:
    ui.need(ui.text_sel(key="selectWifi"), "màn Cấu hình qua bluetooth", ui.WAIT * 3)
    row = ui.row_sel(texts=[wifi])
    b = ui.find(row, WIFI_WAIT)
    for _ in range(MAX_DRAGS if b is None else 0):
        _drag(down=True)
        if b := ui.find(row):
            break
    if b is None:
        raise ActionError(f"thiết bị không thấy wifi {wifi!r}")
    return b


def _device_name() -> str:
    """Tên trên màn cuối: chữ cùng hàng, bên trái công tắc Tắt/Bật."""
    els = parse(U2.dump(), config.APP_PACKAGE)
    sw = next((e for e in els if e.clickable and (e.desc.strip() or e.text.strip()) in ("Tắt", "Bật")), None)
    if sw is None:
        raise ActionError("màn cuối không thấy công tắc Tắt/Bật cạnh tên thiết bị")
    cy = (sw.bounds[1] + sw.bounds[3]) // 2
    names = [e.text.strip() for e in els if e.text.strip() and e.bounds[2] <= sw.bounds[0]
             and e.bounds[1] <= cy <= e.bounds[3] and e.text.strip() != ".."]
    if not names:
        raise ActionError("màn cuối không đọc được tên thiết bị")
    return names[-1]


MODES = {"hub": ["configSensorHS"], "direct": ["neo.configNeoNoHSTitle", "configSensorNotHS"]}


def _wifi_step(ui: Ui, wifi: str | None, password: str | None) -> None:
    if not (wifi and password):
        raise ActionError("thiết bị Wi-Fi: cần wifi + password")
    ui.tap(_wifi_row(ui, wifi))
    ui.need(ui.text_sel(key="inputManualWifi"), "form Nhập thông tin wifi")
    ui.settle()
    box = ui.d(className="android.widget.EditText", instance=1)   # không dùng ui.fill: lỗi của nó in cả giá trị
    box.set_text(password)
    if (box.get_text() or "") != password:
        raise ActionError("ô mật khẩu wifi không nhận chữ")
    ui.hide_keyboard()
    ui.tap(ui.need(ui.text_sel(key="confirm"), "nút Xác nhận"))


def _mode_step(ui: Ui, mode: str | None) -> None:
    if mode not in MODES:
        raise ActionError(f"thiết bị cho chọn loại cấu hình: cần mode = {' | '.join(MODES)}")
    ui.tap(ui.need(ui.row_sel(key=MODES[mode]), f"dòng loại cấu hình {mode!r}"))
    ui.tap(ui.need(ui.text_sel(key="configNextStep"), "nút Tiếp theo"))


def _error_text() -> str:
    t = [e.text.strip() for e in parse(U2.dump(), config.APP_PACKAGE) if e.text.strip()]
    return " · ".join(t[t.index("Nguyên nhân"):] if "Nguyên nhân" in t else t)[:200]


def _set_name(ui: Ui, name: str) -> None:
    box = ui.d(className="android.widget.EditText", instance=0)
    if not box.exists:
        raise ActionError("màn cuối không có ô nhập tên")
    box.set_text(name)
    if (box.get_text() or "").strip() != name.strip():
        raise ActionError(f"ô tên không nhận {name!r}")
    ui.hide_keyboard()


def _set_room(ui: Ui, room: str) -> None:
    els = parse(U2.dump(), config.APP_PACKAGE)
    row = next((e for e in els if e.clickable and e.desc.strip().endswith(", ..")), None)
    if row is None:
        raise ActionError("màn cuối không thấy dòng phòng")
    ui.tap(row.bounds)
    head = ui.need(ui.text_sel(key="selectRoom"), "sheet Chọn phòng")
    ui.settle()
    item = next((e for e in parse(U2.dump(), config.APP_PACKAGE)
                 if e.clickable and e.bounds[1] > head[3] and (e.desc.strip() or e.text.strip()) == room.strip()), None)
    if item is None:
        raise ActionError(f"sheet Chọn phòng không có {room!r}")
    ui.tap(item.bounds)
    ui.gone(ui.text_sel(key="selectRoom"))


def _responses(pos: int, path: str) -> list[dict]:
    """Response JSON của `path` trong flows.jsonl ghi sau vị trí `pos`."""
    with open(config.MITM_FLOWS, "rb") as f:
        f.seek(pos)
        lines = f.read().decode("utf-8", "replace").splitlines()
    out = []
    for line in lines:
        try:
            fl = json.loads(line)
        except ValueError:
            continue
        if path in (fl.get("path") or "") and isinstance(fl.get("resp_body"), dict):
            out.append(fl["resp_body"])
    return out


def config_ble(scout, device: str, wifi: str | None = None, password: str | None = None, restore: bool = False,
               mode: str | None = None, name: str | None = None, room: str | None = None) -> dict:
    """Cấu hình thiết bị `device` (tên ô ở 'Thiết bị có sẵn xung quanh').
    Thiết bị Wi-Fi: `wifi` + `password`. Thiết bị chọn loại cấu hình (NeoR6, cảm biến khói…): `mode` hub | direct.
    Thiết bị từng có cấu hình: restore=False → như thiết bị mới, True → khôi phục cũ. `name` / `room` đặt ở màn cuối.
    Xong dựng lại map của nhà."""
    r = nearby(scout, want=device)
    if not r["found"]:
        raise ActionError(f"{r['rounds']} lượt quét không thấy {device!r}; xung quanh có: {r['devices']}")
    ui = Ui(scout)
    ui.tap(_tile(ui, device))
    kind = _first(ui, [ui.text_sel(key="selectWifi"), ui.text_sel(key="DriverLed.chooseConfigDledAp")], ui.WAIT * 3)
    if kind is None:
        raise ActionError("bấm ô xong không tới màn chọn wifi / chọn loại cấu hình")
    _wifi_step(ui, wifi, password) if kind == 0 else _mode_step(ui, mode)
    recover, done, err = (ui.text_sel(key="configRecover.methodSectionTitle"), ui.text_sel(key="addToSuggestList"),
                          ui.text_sel(key="config.errorTitle"))
    step = _first(ui, [recover, done, err], CONFIG_WAIT)
    recovered = step == 0
    if recovered:
        pick = "configRecover.restoreOldConfigTitle" if restore else "configRecover.configureAsNewTitle"
        ui.tap(ui.need(ui.row_sel(key=pick), "lựa chọn phương thức cấu hình"))
        ui.tap(ui.need(ui.text_sel(key="configNextStep"), "nút Tiếp theo"))
        s2 = _first(ui, [done, err], CONFIG_WAIT)
        step = None if s2 is None else s2 + 1
    if step is None:
        raise ActionError(f"{CONFIG_WAIT:.0f}s chưa tới màn cuối (Hoàn thành)")
    if step == 2:
        raise ActionError(f"Lỗi cấu hình: {_error_text()}")
    if name:
        _set_name(ui, name)
    if room:
        _set_room(ui, room)
    box = ui.d(className="android.widget.EditText", instance=0)
    dev = (box.get_text() or "").strip() if box.exists else _device_name()
    pos = config.MITM_FLOWS.stat().st_size
    cap = MitmCapture(config.EXPORTS, config.MITM_FLOWS)
    cap.start()
    ui.tap(ui.need(ui.text_sel(key="configComplete"), "nút Hoàn thành"))
    if not ui.gone(done, DONE_WAIT):
        bad = [x.get("message") for x in _responses(pos, "/v3/device/updateRoot") if x.get("status") is False]
        raise ActionError(f"bấm Hoàn thành {DONE_WAIT:.0f}s không thoát màn cuối"
                          + (f"; server updateRoot: {bad[-1]!r} (app không báo)" if bad else ""))
    cap.wait_list(timeout=20)
    scout.load(fresh=False)
    return {"device": dev, "recover_step": recovered, "restored": restore if recovered else None,
            "mode": mode if kind == 1 else None, "screen": scout.goto("home"),
            "devices": sorted(n[n.rindex("[") + 1:-1].strip() for n in scout.report.leaves),
            "warnings": scout.report.warnings}
