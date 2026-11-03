"""Lặp tuần hoàn (TIMER_LOOP; swinputv2 bước giây 1 s — Wallpad cycle/swinputv2.md): "Danh sách hẹn giờ tuần hoàn"
→ + → "Tạo tuần hoàn". Khám trên app 4.0.19 ngày 2026-11-03:

  Thời gian bật (phút : giây)   bánh xe phút 0–359 : giây 0–59, cuộn vòng, mở ở 00:01
  Thời gian tắt (phút : giây)   như trên
  Chạy mãi mãi | Giới hạn thời gian
  Giới hạn: Bắt đầu HH:MM, Kết thúc HH:MM (bánh xe giờ 0–23 : phút 0–59, mở ở giờ máy +1 / +2 phút),
            Lặp hàng tuần (công tắc, mặc định bật) + chip T2…CN (mặc định chọn hết);
            tắt Lặp hàng tuần → lịch chọn 1 ngày (dòng hiện "…, 20:00, 23:00, Ngày 03/11/2026")
  Lưu lại   nút nổi cuối màn; tối đa 8 tuần hoàn
"""
from __future__ import annotations

import re
import time

from ..interact import u2 as U2
from .timer import _clock, _date, _days
from .ui import ActionError, Ui, arrive, node


def _mmss(v: str, lo: int = 0) -> tuple[int, int]:
    m, s = map(int, v.split(":"))
    if not (0 <= m <= 359 and 0 <= s <= 59) or m * 60 + s <= lo:
        raise ActionError(f"thời gian {v!r} phải là MM:SS, phút 0–359, giây 0–59, > 0")
    return m, s


def _hhmm(v: str) -> tuple[int, int]:
    h, m = map(int, v.split(":"))
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ActionError(f"giờ {v!r} phải là HH:MM")
    return h, m


def _limited(ui: Ui) -> bool:
    return ui.find(ui.text_sel(key="start")) is not None          # khối Bắt đầu/Kết thúc chỉ có ở chế độ giới hạn


def _switch_near(ui: Ui, key: str):
    label = ui.need(ui.text_sel(key=key), f"dòng {key}")
    cy = (label[1] + label[3]) // 2
    sw = next((e for e in ui.elements()
               if e.cls == "android.widget.Switch" and abs((e.bounds[1] + e.bounds[3]) // 2 - cy) < 60), None)
    if sw is None:
        raise ActionError(f"không thấy công tắc của dòng {key}")
    return sw


def _fill(ui: Ui, cur: dict, on=None, off=None, start=None, end=None, weekly=None, days=None, date=None,
          limit=None) -> None:
    """cur: giá trị bánh xe đang hiện {"on": (m, s), "off": (m, s), "start": (h, m), "end": (h, m)} — tool tự biết
    (thêm: mặc định 00:01 / giờ máy +1/+2; sửa: giá trị trên dòng) → bánh xe trùng giá trị thì không đặt lại.
    Form thêm có lúc giữ giá trị lần mở trước (không lưu) → add_cycle đọc dòng sau khi lưu, lệch thì sửa lại.
    limit: True = Giới hạn thời gian, False = Chạy mãi mãi, None = giữ."""
    save = ui.text_sel(key="save")
    if on or off:                                    # 1. bánh xe bật/tắt: ở đầu form, làm trước khi cuộn
        wheels = sorted(ui.wheels(), key=lambda w: (w[1], w[0]))[:4]     # 2 hàng: bật (phút, giây), tắt (phút, giây)
        if len(wheels) != 4 or wheels[0][1] > 600:
            raise ActionError(f"không thấy 4 bánh xe Thời gian bật/tắt ở đầu form: {wheels}")
        for (wm, ws), want, now in ((wheels[0:2], on, cur.get("on")), (wheels[2:4], off, cur.get("off"))):
            if want:                                 # chỉ đặt bánh xe khác giá trị đang hiện (cur, tool tự biết)
                m, s = _mmss(want)
                if now is None or now[0] != m:
                    ui.set_wheel(wm, m)
                if now is None or now[1] != s:
                    ui.set_wheel(ws, s)
    if limit is not None and limit != _limited(ui):  # 2. chế độ
        key = "timerLoop.modeRunLimit" if limit else "timerLoop.modeRunForever"
        ui.tap(ui.need(ui.text_sel(key=key), f"nút {key}"))
        time.sleep(0.5)
        if _limited(ui) != limit:
            raise ActionError(f"bấm {key} nhưng chế độ không đổi")
    if not (start or end or weekly is not None or days is not None or date):
        return
    if not _limited(ui):
        raise ActionError("start/end/weekly/days/date chỉ có ở chế độ Giới hạn thời gian (limit=True)")
    ui.reveal(ui.text_sel(key="timerLoop.timerLimitNode"), "khối Giới hạn thời gian", save)
    label = ui.need(ui.text_sel(key="start"), "nhãn Bắt đầu")
    wheels = [w for w in ui.wheels() if w[1] > label[3]]
    if len(wheels) != 4:
        raise ActionError(f"thấy {len(wheels)} bánh xe Bắt đầu/Kết thúc, cần 4")
    for (wh, wm), want, now in ((wheels[0:2], start, cur.get("start")), (wheels[2:4], end, cur.get("end"))):
        if want:
            h, m = _hhmm(want)
            if now is None or now[0] != h:
                ui.set_wheel(wh, h)
            if now is None or now[1] != m:
                ui.set_wheel(wm, m)
    if weekly is not None:
        sw = _switch_near(ui, "repeatWeekly")
        if (sw.desc.strip() in ui.texts("turnOn")) != weekly:
            ui.tap(sw.bounds)
            time.sleep(0.5)
    if days is not None:
        _days(ui, days, save)
    if date:                                         # "YYYY-MM-DD", chỉ khi Lặp hàng tuần tắt
        _date(ui, date, save)


def _save(scout, ui: Ui, lst: str) -> None:
    ui.tap(ui.need(ui.text_sel(key="save"), "nút Lưu lại"))
    if not ui.find(ui.text_sel(key="timerLoop.listTimerLoop"), 6.0):
        err = ui.find(ui.text_sel(key=["timerLoop.errorTimeRun", "timerLoop.errorStartStopTime",
                                       "timerLoop.maxLimit"]))
        raise ActionError("bấm Lưu lại nhưng không về danh sách tuần hoàn" + (" (app báo lỗi)" if err else ""))
    arrive(scout, lst)
    time.sleep(0.5)


def list_cycles(scout, device: str) -> list[str]:
    """Mô tả các dòng tuần hoàn đang có."""
    scout.goto(node(scout, "cycle/list", device))
    return _items(Ui(scout))


ITEM = r"(?s)^\D*\d{1,3}:\d{2}\D+\d{1,3}:\d{2}.*"         # dòng: "Thời gian bật 00:01 | Thời gian tắt 09:05 …"


def _items(ui: Ui, wait: float = 3.0) -> list[str]:
    """Dòng tuần hoàn (tải sau khi màn hiện): chờ có dòng HOẶC chữ rỗng 'Ấn dấu " + " để thêm hẹn giờ' (AddAlarm)
    — trước chỉ chờ dòng nên danh sách rỗng mất trọn `wait` (3 s)."""
    item, empty = {"descriptionMatches": ITEM, "clickable": True}, ui.text_sel(key="AddAlarm")
    end = time.monotonic() + wait
    while time.monotonic() < end and not (U2.locate(item) or U2.locate(empty)):
        time.sleep(0.1)
    return [e.desc for e in ui.elements() if e.clickable and re.match(ITEM, e.desc)]


def add_cycle(scout, device: str, on: str = "00:01", off: str = "00:01", start: str | None = None,
              end: str | None = None, weekly: bool | None = None, days: list[str] | None = None,
              date: str | None = None, save: bool = True) -> dict:
    """Thêm tuần hoàn bật `on` / tắt `off` (MM:SS). Có start/end/weekly/days/date → chế độ Giới hạn thời gian
    (date "YYYY-MM-DD" cần weekly=False).

    Form mở KHÔNG chắc ở 00:01: bánh xe giữ vị trí của lần mở trước (đã gặp: lần trước kéo giây lên 06 rồi
    bỏ không lưu → lần sau mở ở 06, lưu ra lệch +5). Bánh xe không lộ số → lưu xong đọc dòng mới trong danh sách,
    lệch thì mở dòng đó sửa lại (form sửa mở đúng giá trị của dòng)."""
    _mmss(on), _mmss(off)
    lst, add = node(scout, "cycle/list", device), node(scout, "cycle/add", device)
    scout.goto(lst)
    old = _items(Ui(scout))
    ui = None
    for _ in range(2):                               # Bắt đầu/Kết thúc mở theo giờ máy → đọc đồng hồ trước/sau
        if scout.nav.cur == add:
            scout.goto(lst)
        before = _clock(Ui(scout))
        scout.goto(add)
        ui = Ui(scout)
        if _clock(ui) == before:
            break
    t = before[0] * 60 + before[1]
    cur = {"on": (0, 1), "off": (0, 1), "start": divmod((t + 1) % 1440, 60), "end": divmod((t + 2) % 1440, 60)}
    limit = True if (start or end or weekly is not None or days is not None or date) else None
    _fill(ui, cur, on=on, off=off, start=start, end=end, weekly=weekly, days=days, date=date, limit=limit)
    if not save:
        return {"saved": False}
    _save(scout, ui, lst)
    items = _items(ui)
    new = list(items)
    for d in old:
        if d in new:
            new.remove(d)
    if len(new) != 1:
        raise ActionError(f"đã lưu nhưng không xác định được dòng mới: trước {old}, sau {items}")
    got = parse_item(new[0])
    fix = {k: v for k, v in (("on", f"{_mmss(on)[0]:02d}:{_mmss(on)[1]:02d}"),
                             ("off", f"{_mmss(off)[0]:02d}:{_mmss(off)[1]:02d}")) if got[k] != v}
    for k, want, i in (("start", start, 0), ("end", end, 1)):
        if want and (len(got["times"]) <= i or got["times"][i] != f"{_hhmm(want)[0]:02d}:{_hhmm(want)[1]:02d}"):
            fix[k] = want
    if fix:
        out = edit_cycle(scout, device, items.index(new[0]), **fix)
        out["fixed"] = {k: got.get(k) for k in fix if k in got} | {"times": got["times"]}
        return out
    return {"saved": True, "items": items}


# ---- dòng trong danh sách: "Thời gian bật 00:01 | Thời gian tắt 09:05 (phút:giây), Chạy mãi mãi" ----

def parse_item(desc: str) -> dict:
    """→ {"on": "MM:SS", "off": "MM:SS", "times": [các HH:MM còn lại, vd Bắt đầu/Kết thúc], "desc": desc}."""
    t = re.findall(r"\b(\d{1,3}:\d{2})\b", desc)
    if len(t) < 2:
        raise ActionError(f"không đọc được thời gian bật/tắt trong {desc!r}")
    return {"on": t[0], "off": t[1], "times": t[2:], "desc": desc}


def _open(scout, device: str, index: int) -> tuple[Ui, str, dict]:
    lst = node(scout, "cycle/list", device)
    scout.goto(lst)
    ui = Ui(scout)
    _items(ui)
    rows = [e for e in ui.elements() if e.clickable and re.match(ITEM, e.desc)]
    if not 0 <= index < len(rows):
        raise ActionError(f"không có tuần hoàn thứ {index} (đang có {len(rows)})")
    item = parse_item(rows[index].desc)
    ui.tap(rows[index].bounds)
    ui.need(ui.text_sel(key="timerLoop.turnOnTime"), "form tuần hoàn", 4.0)
    arrive(scout, node(scout, "cycle/add", device))
    time.sleep(0.4)
    return ui, lst, item


def edit_cycle(scout, device: str, index: int = 0, **changes) -> dict:
    """Sửa tuần hoàn thứ `index` (0 = dòng đầu). changes: on, off, start, end, weekly, days, date, limit — chỉ đổi cái
    được truyền. Bánh xe mở ở giá trị của dòng (bật/tắt; Bắt đầu/Kết thúc lấy từ chữ dòng nếu có)."""
    ui, lst, item = _open(scout, device, index)
    cur = {"on": _mmss(item["on"], -1), "off": _mmss(item["off"], -1)}
    if len(item["times"]) >= 2:
        cur["start"], cur["end"] = _hhmm(item["times"][0]), _hhmm(item["times"][1])
    if changes.get("limit") is None and any(changes.get(k) is not None for k in ("start", "end", "weekly", "days",
                                                                                  "date")):
        changes["limit"] = True
    _fill(ui, cur, **changes)
    _save(scout, ui, lst)
    return {"saved": True, "items": _items(ui)}


def delete_cycle(scout, device: str, index: int = 0) -> dict:
    """Xoá tuần hoàn thứ `index`: mở form → thùng rác góc phải header → xác nhận (nếu app hỏi)."""
    ui, lst, item = _open(scout, device, index)
    w = ui.d.window_size()[0]
    ui.d.click(w - 72, 207)
    btn = ui.find(ui.text_sel(key=["confirm", "delete", "ok"]), 2.0)
    if btn and not ui.find(ui.text_sel(key="timerLoop.listTimerLoop")):
        ui.tap(btn)
    if not ui.find(ui.text_sel(key="timerLoop.listTimerLoop"), 6.0):
        raise ActionError("bấm xoá nhưng không về danh sách tuần hoàn")
    arrive(scout, lst)
    time.sleep(0.5)
    items = _items(ui, 1.0)
    if item["desc"] in items:
        raise ActionError(f"đã xoá nhưng vẫn còn {item['desc']!r}")
    return {"deleted": item["desc"], "items": items}
