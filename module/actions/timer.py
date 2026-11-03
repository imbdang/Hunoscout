"""Hẹn giờ của một thiết bị (TimerKind Basic: swinputv2 và các công tắc) — thêm / sửa / xoá / liệt kê.

Form (EditAlarmNew, "Thêm/Sửa hẹn giờ <tên>"), theo app 4.0.19 + Wallpad timer/kinds/basic:
  Loại hẹn giờ   Thời gian | Mặt trời mọc | Mặt trời lặn (mặt trời: không có giờ:phút)
  Thời gian      2 bánh xe giờ 0–23 : phút 0–59; bấm số giữa bánh xe → hộp thoại nhập số (Ui.set_wheel)
  Hành động      Bật | Tắt | Khoá trẻ em | Mở khoá trẻ em  (dòng hiện chữ IN HOA)
  Chạy hẹn giờ sau khi thiết bị online   công tắc
  Chế độ lặp     Một ngày (lịch) | Lặp hàng tuần (chip T2…CN) | Lặp hàng tháng (ô 1–31 / Ngày cuối tháng)
  Lưu lại        nút nổi đè cuối form; lưu xong app về danh sách
"""
from __future__ import annotations

import re
import time

from .ui import ActionError, Ui, arrive, node

KIND = {"time": "time", "sunrise": "sunrise", "sunset": "sunset"}
ACTION = {"on": "turnOn", "off": "turnOff", "child_lock": "alarmLock", "child_unlock": "alarmUnlock"}
REPEAT = {"once": "aDay", "weekly": "repeatWeekly", "monthly": "repeatMonthly"}
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
ITEM = r"(?s)^\s*(\d{1,2}):(\d{2}).*"                  # dòng hẹn giờ trong danh sách: "13:23,  - Bật"
ROW = re.compile(r"(?s)^[^,]+, +- ")                    # mọi dòng hẹn giờ (kể cả mặt trời): "<giờ|loại>,  - <hành động>…"


# ---- danh sách ----

def _items(ui: Ui, wait: float = 3.0) -> list[str]:
    """Dòng hẹn giờ (danh sách tải SAU khi màn hiện → chờ có dòng hoặc chữ "Ấn dấu + để thêm hẹn giờ")."""
    ui.find({"descriptionMatches": r"(?s)^[^,]+, +- .*", "clickable": True}, wait) \
        or ui.find(ui.text_sel(key="AddAlarm"), 1.0)
    return [e.desc for e in ui.elements() if e.clickable and ROW.match(e.desc)]


def list_timers(scout, device: str) -> list[str]:
    """Mô tả các dòng hẹn giờ đang có, vd ["13:23,  - Bật"]."""
    scout.goto(node(scout, "timer/list", device))
    return _items(Ui(scout))


def _item_sel(ui: Ui, existing: str) -> dict:
    """Dòng hẹn giờ theo "HH:MM", hoặc theo loại mặt trời ("sunrise" | "sunset") — dòng đó không có giờ."""
    if existing in KIND:
        return ui.row_sel(key=KIND[existing])
    h, m = map(int, existing.split(":"))
    return {"descriptionMatches": rf"(?s)^\s*0?{h}:{m:02d}\b.*", "clickable": True}


def _open_item(scout, ui: Ui, existing: str) -> None:
    b = ui.need(_item_sel(ui, existing), f"hẹn giờ {existing}")
    ui.d.click(min(400, b[2] - 200), (b[1] + b[3]) // 2)        # phần chữ giờ, tránh công tắc bên phải
    ui.need(ui.text_sel(key="editAlarm", prefix=True), "màn Sửa hẹn giờ", 4.0)


# ---- form ----

def _desc(ui: Ui, sel: dict) -> str:
    return ui.d(**sel).info["contentDescription"]


def _is(ui: Ui, desc: str, key: str, upper: bool = False) -> bool:
    head = desc.split(",")[0].strip()
    return head in ({t.upper() for t in ui.texts(key)} if upper else set(ui.texts(key)))


def _fill(ui: Ui, current: tuple[int, int] | None, at=None, kind=None, action=None, run_online=None,
          repeat=None, days=None, monthday=None, last_day=False, date=None) -> None:
    save = ui.text_sel(key="save")
    if kind:                                     # 1. loại hẹn giờ
        row = ui.row_sel(key=list(KIND.values()))
        if not _is(ui, _desc(ui, row), KIND[kind]):
            ui.tap_clear(row, "dòng Loại hẹn giờ", save)
            ui.pick(KIND[kind], what=f"loại {kind}")
    if at and kind in (None, "time"):            # 2. giờ:phút — bấm số giữa bánh xe → điền thẳng (không cuộn)
        h, m = map(int, at.split(":"))
        wheels = ui.wheels()
        if len(wheels) != 2:
            raise ActionError(f"thấy {len(wheels)} bánh xe, cần 2 (giờ, phút)")
        if current is None or current[0] != h:   # current: giờ form đang hiện (thêm: giờ máy +1; sửa: giờ của dòng)
            ui.set_wheel(wheels[0], h)
        if current is None or current[1] != m:
            ui.set_wheel(wheels[1], m)
    if action:                                   # 3. hành động — dòng hiện chữ IN HOA
        row = ui.row_sel(texts=sorted({t.upper() for k in ACTION.values() for t in ui.texts(k)}))
        if not _is(ui, _desc(ui, row), ACTION[action], upper=True):
            ui.tap_clear(row, "dòng Hành động", save)
            ui.pick(ACTION[action], what=f"hành động {action}")
    if run_online is not None:                   # 4. chạy sau khi thiết bị online
        label = ui.need(ui.text_sel(key="runTimerWhenReconnected"), "dòng Chạy hẹn giờ sau khi online")
        cy = (label[1] + label[3]) // 2
        sw = next((e for e in ui.elements()
                   if e.cls == "android.widget.Switch" and abs((e.bounds[1] + e.bounds[3]) // 2 - cy) < 60), None)
        if sw is None:
            raise ActionError("không thấy công tắc Chạy hẹn giờ sau khi online")
        if (sw.desc.strip() in ui.texts("turnOn")) != run_online:
            ui.tap(sw.bounds)
            time.sleep(0.4)
    if kind in ("sunrise", "sunset"):            # 5. mặt trời: form ẩn dòng Chế độ lặp, chỉ còn chip thứ
        if days is not None:
            _days(ui, days, ui.text_sel(key="save"))
    elif repeat:                                 # 5. chế độ lặp
        row = ui.row_sel(key=list(REPEAT.values()))
        if not _is(ui, _desc(ui, row), REPEAT[repeat]):
            ui.tap_clear(row, "dòng Chế độ lặp", save)
            ui.pick(REPEAT[repeat], what=f"lặp {repeat}")
        if repeat == "weekly" and days is not None:
            _days(ui, days, save)
        elif repeat == "monthly":
            _monthday(ui, monthday, last_day, save)
        elif repeat == "once" and date:
            _date(ui, date, save)


def _days(ui: Ui, days: list[str], save: dict) -> None:
    want = set(days)
    if not want or want - set(DAYS):
        raise ActionError(f"days phải là tập con khác rỗng của {DAYS}")
    sels = [ui.option_sel(key=k) for k in DAYS]
    ui.reveal(sels[-1], "chip CN", save)                     # hàng chip nằm cuối form, dưới nút Lưu
    els = ui.elements()                                       # 1 dump cho cả 7 chip (7 lần hỏi máy ~1.5 s)
    boxes = []
    for sel, k in zip(sels, DAYS):
        rx = re.compile(sel["descriptionMatches"])
        b = next((e.bounds for e in els if e.clickable and rx.match(e.desc)), None)
        if b is None:
            raise ActionError(f"không thấy chip {k}")
        boxes.append(b)
    for k, b, on in zip(DAYS, boxes, ui.green(boxes)):
        if (k in want) != on:
            ui.tap(b)
            time.sleep(0.25)
    got = {k for k, on in zip(DAYS, ui.green(boxes)) if on}
    if got != want:
        raise ActionError(f"chọn thứ {sorted(want)} nhưng màn đang chọn {sorted(got)}")


def _monthday(ui: Ui, day: int | None, last_day: bool, save: dict) -> None:
    if last_day:
        ui.tap_clear(ui.text_sel(key="lastDayOfMonth"), "Ngày cuối tháng", save)
    elif day:
        ui.tap_clear(ui.option_sel(text=str(day)), f"ngày {day} trong tháng", save)
    time.sleep(0.3)


def _date(ui: Ui, date: str, save: dict) -> None:
    """date "YYYY-MM-DD": lật lịch tới đúng tháng (nhãn "Tháng 11 - Năm 2026") rồi chọn ngày."""
    y, mo, d = map(int, date.split("-"))
    month = re.compile(r"^\D*(\d{1,2})\D+(\d{4})?\D*$")     # lịch tuần hoàn tách "Tháng 11 - Năm" | "2026"
    for _ in range(24):
        els = ui.elements()
        lb = next((e for e in els if month.match(e.text.strip())), None)
        if lb is None:
            raise ActionError("không thấy nhãn tháng của lịch")
        cy = (lb.bounds[1] + lb.bounds[3]) // 2
        mm = month.match(lb.text.strip())
        year = mm.group(2) or next((e.text.strip() for e in els if re.fullmatch(r"\d{4}", e.text.strip())
                                    and abs((e.bounds[1] + e.bounds[3]) // 2 - cy) < 40), None)
        if year is None:
            raise ActionError(f"không đọc được năm của lịch (nhãn {lb.text!r})")
        cur_m, cur_y = int(mm.group(1)), int(year)
        if (cur_y, cur_m) == (y, mo):
            break
        arrows = [e.bounds for e in els if e.clickable and abs((e.bounds[1] + e.bounds[3]) // 2 - cy) < 60]
        nxt = (cur_y, cur_m) < (y, mo)
        ui.tap(max(arrows) if nxt else min(arrows))
        time.sleep(0.5)
    else:
        raise ActionError(f"không lật được lịch tới tháng {mo}/{y}")
    ui.tap_clear(ui.option_sel(text=str(d)), f"ngày {d}", save)
    time.sleep(0.3)


def _save(scout, ui: Ui, list_node: str) -> None:
    ui.tap(ui.need(ui.text_sel(key="save"), "nút Lưu lại"))
    ok = ui.find(ui.text_sel(key=["normalTimer", "timer"], prefix=True), 6.0)
    if not ok:
        raise ActionError("bấm Lưu lại nhưng không về danh sách hẹn giờ (form báo lỗi?)")
    arrive(scout, list_node)
    time.sleep(0.5)


def _clock(ui: Ui) -> tuple[int, int]:
    h, m = ui.d.shell("date +%H:%M").output.strip().split(":")
    return int(h), int(m)


# ---- thêm / sửa / xoá ----

def add_timer(scout, device: str, at: str | None = None, action: str = "on", kind: str = "time",
              repeat: str = "weekly", days: list[str] | None = None, monthday: int | None = None,
              last_day: bool = False, date: str | None = None, run_online: bool = True, save: bool = True) -> dict:
    """Thêm hẹn giờ. Bánh xe mở ra ở giờ hiện tại của máy → đọc đồng hồ máy trước/sau khi vào form
    (khác phút = không chắc bánh xe đang ở phút nào → vào lại form)."""
    lst, add = node(scout, "timer/list", device), node(scout, "timer/add", device)
    ui = None
    for _ in range(2):
        if scout.nav.cur == add:                 # đang ở form cũ → về danh sách cho form mở lại giờ mới
            scout.goto(lst)
        before = _clock(Ui(scout))
        scout.goto(add)
        ui = Ui(scout)
        if _clock(ui) == before:
            break
    start = divmod(before[0] * 60 + before[1] + 1, 60)        # form mở ở giờ hiện tại + 1 phút (đo trên app)
    start = (start[0] % 24, start[1])
    _fill(ui, start, at=at, kind=kind, action=action, run_online=run_online, repeat=repeat, days=days,
          monthday=monthday, last_day=last_day, date=date)
    if not save:
        return {"saved": False}
    _save(scout, ui, lst)
    items = _items(ui)
    if at and kind == "time" and not any(_at(i) == at for i in items):
        # đổi phút đúng lúc mở form → bánh xe lệch 1–2 phút: tìm dòng vừa tạo (gần giờ muốn) rồi sửa lại
        t = int(at[:2]) * 60 + int(at[3:])
        near = [i for i in items if _at(i) and 0 < abs(int(_at(i)[:2]) * 60 + int(_at(i)[3:]) - t) <= 2]
        if len(near) != 1:
            raise ActionError(f"đã lưu nhưng danh sách không có {at}: {items}")
        return edit_timer(scout, device, _at(near[0]), at=at)
    return {"saved": True, "items": items}


def _at(item: str) -> str | None:
    m = re.match(ITEM, item)
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else None


def edit_timer(scout, device: str, existing: str, **changes) -> dict:
    """Sửa hẹn giờ đang có lúc `existing` ("HH:MM"). changes: at (giờ mới), action, kind, repeat, days, monthday,
    last_day, date, run_online — chỉ đổi cái được truyền."""
    lst = node(scout, "timer/list", device)
    scout.goto(lst)
    ui = Ui(scout)
    _open_item(scout, ui, existing)
    _fill(ui, None if existing in KIND else tuple(map(int, existing.split(":"))), **changes)
    _save(scout, ui, lst)
    return {"saved": True, "items": _items(ui)}


def delete_timer(scout, device: str, at: str) -> dict:
    """Xoá hẹn giờ lúc `at` ("HH:MM" | "sunrise" | "sunset"): mở màn sửa → thùng rác trên header → xác nhận."""
    lst = node(scout, "timer/list", device)
    scout.goto(lst)
    ui = Ui(scout)
    _open_item(scout, ui, at)
    w = ui.d.window_size()[0]
    ui.d.click(w - 72, 207)                      # thùng rác góc phải header (1094–1202, 154–262)
    ui.need(ui.text_sel(key="messageDeleteAlarm"), "hộp thoại xác nhận xoá", 3.0)
    btn = ui.find({"textMatches": ui.text_sel(key=["confirm", "delete", "ok"])["textMatches"]}, 1.0)
    if btn is None:
        raise ActionError("không thấy nút xác nhận trong hộp thoại xoá")
    ui.tap(btn)
    if not ui.find(ui.text_sel(key=["normalTimer", "timer"], prefix=True), 6.0):
        raise ActionError("xác nhận xoá nhưng không về danh sách hẹn giờ")
    arrive(scout, lst)
    time.sleep(0.5)
    items = _items(ui)
    if ui.find(_item_sel(ui, at)):
        raise ActionError(f"đã xác nhận xoá nhưng {at} vẫn còn: {items}")
    return {"deleted": True, "items": items}
