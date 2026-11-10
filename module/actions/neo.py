"""NeoR6 (scenario_sw6): liên kết thiết bị trung gian, hành vi nút (điều khiển thiết bị), gỡ liên kết ở thiết bị đích.

Đi tay 2026-11-05 (app 4.0.23, fw 260512, nhà Homekit Pro, đích Ổ cắm 3):
- Liên kết thiết bị trung gian = NeoR6 "ký sinh" lên công tắc Wi-Fi (phát beacon, công tắc đưa lên mạng). Dòng ở màn
  chi tiết (desc ".., Liên kết thiết bị trung gian, <tên | Chưa liên kết>, ..") → "Danh sách thiết bị" (dòng
  "<tên>, <root_id>" + ô chọn) → chọn → Liên kết (khoá tới khi chọn) → updateDataExtra → app tự về màn chi tiết.
  Đã liên kết: màn hiện "Danh sách thiết bị đã liên kết" + nút "Xoá liên kết" → gỡ xong app Ở LẠI màn (danh sách
  chưa liên kết). Gỡ trung gian không xoá hành vi điều khiển thiết bị của nút.
- Nút (mặt trời … lục giác): tab Nhấn 1 lần / 2 lần / giữ → "Thiết bị đã chọn" → sheet "Chọn hành động" →
  Điều khiển thiết bị → "Chọn thiết bị": bấm ô xoay vòng Không chọn → Đảo trạng thái → Bật → Tắt → Lưu lại (để Không
  chọn → "Bạn chưa chọn thiết bị nào") → về màn nút → Lưu lại (~3 s quay) → banner "Thành công", updateDataExtra.
  Trên màn nút, bấm dòng thiết bị đã gán cũng xoay vòng nhưng chỉ Đảo → Bật → Tắt.
  Kích hoạt ngữ cảnh chạy khi ấn: cần liên kết trung gian ("Bạn phải liên kết thiết bị trung gian trước!") → "Chọn ngữ
  cảnh" (ô ngữ cảnh chạy khi ấn của nhà; đang chọn = desc ".., <tên>" + dấu tick, chọn nhiều được) → Lưu lại → màn nút
  "Ngữ cảnh đã chọn: <tên>" → Lưu lại → "Thành công" (POST /v3/collection/add; bỏ hết rồi lưu = /v3/collection/update,
  nút về "Chưa có hành động").
- Gỡ hành vi: ở THIẾT BỊ ĐÍCH → dòng "Liên kết công tắc ngữ cảnh" (hiện muộn ~2 s, chỉ khi đã liên kết, "Đã liên kết: n")
  → dòng NeoR6 → thùng rác SVG bên phải (không có trong cây UI) → Xoá → "Huỷ liên kết thành công!" (2 updateDataExtra).
  Gỡ ở đây xoá CẢ hành vi nút LẪN liên kết trung gian của NeoR6.
"""
from __future__ import annotations

import time

from .ui import ActionError, Ui, arrive, node

BUTTONS = {"sun": "neo.sun", "moon": "neo.moon", "star": "neo.star", "square": "neo.square",
           "triangle": "neo.triangle", "hexagon": "neo.hexagon"}
PRESS = {"1": "neo.press1Time", "2": "neo.press2Times", "hold": "neo.longPress"}
STATE = {"toggle": "neo.toggle", "on": "on", "off": "off"}
SAVE_WAIT = 15.0      # Lưu lại hành vi nút ~3 s
LINK_ROW_WAIT = 5.0   # dòng "Liên kết công tắc ngữ cảnh" ở thiết bị đích hiện ~2 s sau khi mở màn
TRASH_DX = 94         # thùng rác: cách mép phải dòng ~94 px (dòng 36–1184, icon tâm ~1090)


def _parts(desc: str) -> list[str]:
    return [p.strip() for p in desc.split(",") if p.strip() and p.strip() != ".."]


def _row(ui: Ui, key: str | None = None, text: str | None = None, timeout: float = 0.0):
    """Phần tử bấm được có phần đầu mô tả (bỏ '..') là chữ của `key` / `text` → (parts, bounds) hoặc None."""
    want = set(ui.texts(key, text))
    end = time.monotonic() + timeout
    while True:
        for e in ui.elements():
            p = _parts(e.desc)
            if e.clickable and p and p[0] in want:
                return p, e.bounds
        if time.monotonic() >= end:
            return None
        time.sleep(0.3)


def _need_row(ui: Ui, what: str, timeout: float = Ui.WAIT, **kw):
    r = _row(ui, timeout=timeout, **kw)
    if r is None:
        raise ActionError(f"không thấy {what}")
    return r


def _back_to(scout, nid: str, timeout: float = 6.0) -> None:
    """App tự quay về / vừa Back về màn `nid` (form không phải cạnh của graph) → chờ nhận ra rồi đặt 📍."""
    end = time.monotonic() + timeout
    while scout.nav.where() != nid:
        if time.monotonic() > end:
            raise ActionError(f"không về được {nid} (đang ở {scout.nav.cur})")
        time.sleep(0.3)
    arrive(scout, nid)


def get_neo(scout, device: str) -> dict:
    """Thiết bị trung gian đang liên kết ('' = chưa) + chữ phụ của 6 dòng nút (kiểu nhấn đã gán / Chưa chọn hành động)."""
    scout.goto(node(scout, "infoDevice@", device))
    ui = Ui(scout)
    ui.reach(ui.text_sel(key="neo.linkIntermediateSwitch"), "dòng Liên kết thiết bị trung gian")
    link, _ = _need_row(ui, "dòng Liên kết thiết bị trung gian", key="neo.linkIntermediateSwitch")
    none = set(ui.texts("WCRoom.notLink"))
    out = {"intermediate": "" if len(link) < 2 or link[1] in none else link[1], "buttons": {}}
    for b, key in BUTTONS.items():
        ui.reach(ui.row_sel(key=key), f"dòng {key}")
        r = _row(ui, key=key)
        out["buttons"][b] = r[0][1:] if r else None
    return out


def link_intermediate(scout, device: str, host: str) -> str:
    """Liên kết NeoR6 `device` với thiết bị trung gian `host` → tên trung gian dòng màn chi tiết hiện sau đó."""
    scout.goto(node(scout, "linkIntermediate@", device))
    ui = Ui(scout)
    if ui.find(ui.text_sel(key="neo.listDeviceLinked"), 1.5):
        if _row(ui, text=host, timeout=1.0):
            return host
        raise ActionError("NeoR6 đang liên kết thiết bị trung gian khác — gỡ trước (neo-unlink)")
    _, b = _need_row(ui, f"thiết bị trung gian {host!r} trong danh sách", text=host)
    ui.tap(b)
    ui.tap(ui.need(ui.text_sel(key="deviceLink"), "nút Liên kết"))
    _back_to(scout, node(scout, "infoDevice@", device))
    return get_neo(scout, device)["intermediate"]


def unlink_intermediate(scout, device: str) -> str:
    """Gỡ liên kết thiết bị trung gian → chữ dòng sau đó ('' = chưa liên kết)."""
    scout.goto(node(scout, "linkIntermediate@", device))
    ui = Ui(scout)
    if not ui.find(ui.text_sel(key="neo.listDeviceLinked"), 1.5):
        return get_neo(scout, device)["intermediate"]
    ui.tap(ui.need(ui.text_sel(key="WCRoom.deleteLink"), "nút Xoá liên kết"))
    ok = ui.option_sel(key="delete")                          # hộp xác nhận (nếu có): nút "Xoá"
    if ui.find(ok, 2.0):
        ui.settle()
        ui.tap(ui.need(ok, "nút Xoá"))
    ui.need(ui.text_sel(key="listDevice"), "danh sách chưa liên kết sau khi gỡ", 6.0)   # app ở lại màn này
    ui.d.press("back")
    _back_to(scout, node(scout, "infoDevice@", device))
    return get_neo(scout, device)["intermediate"]


def _cycle(ui: Ui, find, want: set[str], what: str, tries: int = 4) -> None:
    """Bấm ô tới khi phần cuối mô tả ∈ `want` (chữ của trạng thái ở mọi ngôn ngữ; vòng xoay trạng thái)."""
    for _ in range(tries + 1):
        r = find()
        if r is None:
            raise ActionError(f"không thấy {what}")
        if r[0][-1] in want:
            return
        ui.tap(r[1])
        time.sleep(0.6)
    raise ActionError(f"{what}: bấm {tries} lần không ra {sorted(want)}")


def set_button(scout, device: str, button: str, press: str, target: str, state: str) -> dict:
    """Gán cho nút `button` (sun|moon|star|square|triangle|hexagon) kiểu nhấn `press` (1|2|hold): điều khiển thiết bị
    `target` với `state` (toggle|on|off) → Lưu lại."""
    if state not in STATE:
        raise ActionError(f"state ∈ {list(STATE)}")
    ui, bnode = _open_tab(scout, device, button, press)
    want = set(ui.texts(STATE[state]))
    assigned = lambda: _row(ui, text=target)
    if assigned() is None:                                       # chưa gán thiết bị này → màn Chọn thiết bị
        ui.tap(_need_row(ui, "dòng Thiết bị đã chọn", key="neo.selectDevice")[1])
        ui.tap(ui.settled(ui.text_sel(key="controlDeviceText"), "Điều khiển thiết bị"))
        ui.need(ui.text_sel(key="selectDevice"), "màn Chọn thiết bị")
        _cycle(ui, lambda: _row(ui, text=target, timeout=Ui.WAIT), want, f"ô {target!r} (màn Chọn thiết bị)")
        ui.tap(ui.need(ui.text_sel(key="save"), "Lưu lại (Chọn thiết bị)"))
        ui.need(ui.text_sel(key=BUTTONS[button]), "màn nút sau khi chọn thiết bị")
    _cycle(ui, assigned, want, f"dòng {target!r} (màn nút)", tries=3)
    _save(ui, bnode, scout)
    return {"button": button, "press": press, "target": target, "state": state}


def _open_tab(scout, device: str, button: str, press: str) -> tuple[Ui, str]:
    if button not in BUTTONS or press not in PRESS:
        raise ActionError(f"button ∈ {list(BUTTONS)}, press ∈ {list(PRESS)}")
    bnode = node(scout, f"button.{button}@", device)
    scout.goto(bnode)
    ui = Ui(scout)
    ui.tap(ui.need(ui.text_sel(key=PRESS[press]), "tab kiểu nhấn"))
    time.sleep(0.4)
    return ui, bnode


def _save(ui: Ui, bnode: str, scout) -> None:
    ui.tap(ui.need(ui.text_sel(key="save"), "Lưu lại"))
    if not ui.find(ui.text_sel(key="success"), SAVE_WAIT):
        raise ActionError(f"{SAVE_WAIT:.0f}s không thấy 'Thành công' sau Lưu lại")
    arrive(scout, bnode)


def set_button_scenes(scout, device: str, button: str, press: str, scenes: list[str] | None = None) -> dict:
    """Gán cho nút `button` kiểu nhấn `press` đúng tập ngữ cảnh chạy khi ấn `scenes` ([] = bỏ hết) → Lưu lại.
    Cần đã liên kết thiết bị trung gian."""
    ui, bnode = _open_tab(scout, device, button, press)
    ui.tap(_need_row(ui, "dòng Thiết bị đã chọn", key="neo.selectDevice")[1])
    ui.tap(ui.settled(ui.text_sel(key="neo.selectCollectionBase"), "Kích hoạt ngữ cảnh chạy khi ấn"))
    if ui.find(ui.text_sel(key="neo.requireLinkIntermediate"), 1.0):
        raise ActionError("NeoR6 chưa liên kết thiết bị trung gian — liên kết trước (neo-link)")
    ui.need(ui.text_sel(key="selectCollection"), "màn Chọn ngữ cảnh")
    want = {x.strip() for x in scenes or []}
    tiles = [(e, _parts(e.desc)) for e in ui.elements() if e.clickable and _parts(e.desc)
             and e.bounds[1] > ui.need(ui.text_sel(key="selectCollection"), "Chọn ngữ cảnh")[3]]
    names = [p[0] for _, p in tiles]
    if want - set(names):
        raise ActionError(f"không có ngữ cảnh {sorted(want - set(names))}; có: {names}")
    for e, p in tiles:
        if e.desc.strip().startswith("..") != (p[0] in want):    # đang chọn = desc bắt đầu bằng dấu tick
            ui.tap(e.bounds)
            time.sleep(0.4)
    ui.tap(ui.need(ui.text_sel(key="save"), "Lưu lại (Chọn ngữ cảnh)"))
    ui.need(ui.text_sel(key=BUTTONS[button]), "màn nút sau khi chọn ngữ cảnh")
    _save(ui, bnode, scout)
    return {"button": button, "press": press, "scenes": sorted(want)}


def unlink_target(scout, target: str, neo: str) -> str:
    """Ở thiết bị đích `target`: gỡ NeoR6 `neo` khỏi 'Liên kết công tắc ngữ cảnh' (xoá hành vi nút + liên kết trung
    gian) → chữ phụ dòng sau đó ('' = dòng đã ẩn)."""
    info = node(scout, "infoDevice@", target)
    scout.goto(info)
    ui = Ui(scout)
    r = _row(ui, key="neo.contextButtonLink", timeout=LINK_ROW_WAIT)
    if r is None:
        ui.reach(ui.text_sel(key="neo.contextButtonLink"), "dòng Liên kết công tắc ngữ cảnh")
        r = _need_row(ui, "dòng Liên kết công tắc ngữ cảnh", key="neo.contextButtonLink")
    ui.tap(r[1])
    ui.need(ui.text_sel(key="listDevice"), "màn Liên kết công tắc ngữ cảnh")
    _, b = _need_row(ui, f"NeoR6 {neo!r} trong danh sách", text=neo)
    ui.tap((b[2] - TRASH_DX - 30, (b[1] + b[3]) // 2 - 30, b[2] - TRASH_DX + 30, (b[1] + b[3]) // 2 + 30))
    ui.settle()
    ui.tap(ui.need(ui.option_sel(key="delete"), "nút Xoá"))
    if not ui.find(ui.text_sel(key="noDeviceFound"), 6.0) and _row(ui, text=neo):
        raise ActionError(f"xoá xong vẫn còn {neo!r}")
    ui.d.press("back")
    _back_to(scout, info)
    r = _row(ui, key="neo.contextButtonLink", timeout=LINK_ROW_WAIT)
    return r[0][1] if r and len(r[0]) > 1 else ""
