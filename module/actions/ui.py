"""Thao tác trong form / sheet SAU KHI đã route tới màn: tìm theo chữ (i18n), tap tránh nút nổi, chọn trong sheet,
điền chữ, kéo bánh xe số, đọc trạng thái bằng màu. Không biết gì về feature cụ thể (xem timer.py, lock.py, share.py).

Đã thấy trên app 4.0.19:
- Sheet (bottom sheet) KHÔNG đóng bằng Back. Sheet chọn có dòng "Huỷ"; sheet khoá thì không → vuốt xuống.
- Nút "Lưu lại" nổi đè lên cuối form → dòng nằm dưới nó phải cuộn form lên trước khi tap (tap trúng = lưu luôn).
- Bánh xe giờ/phút (WheelPicker native, cuộn vòng, 5 mục) không lộ số trong cây UI; mỗi nấc = cao/5 px,
  kéo chậm + đứng yên rồi nhả → tự khớp đúng nấc. Kéo lên = tăng.
- Chip ngày / dấu ✓ quyền không lộ selected/checked → đọc bằng màu (xanh = đang chọn).
"""
from __future__ import annotations

import time

from .. import config
from ..interact import u2 as U2
from ..ui_map.element import Element, parse
from ..ui_map.locate import _jre, spec_selector
from ..ui_map.scroll import reach as _reach


class ActionError(RuntimeError):
    """Không làm được thao tác: không thấy nút, sheet không mở, giá trị sau khi lưu không khớp…"""


def _rx(texts: list[str], prefix: bool = False) -> str:
    alts = "|".join(_jre(t) for t in texts)
    return r"(?s)^\s*(?:" + alts + (r").*$" if prefix else r")\s*$")


class Ui:
    SCROLL_X = 1195      # cột trống bên phải form (dòng chỉ tới x≈1160): kéo ở đây để cuộn, không chạm trúng gì
    WAIT = 3.0

    def __init__(self, scout):
        self.s, self.lex = scout, scout.nav.lex
        self.d = U2._dev()

    # ---- chữ → selector ----
    def texts(self, key: str | list[str] | None = None, text: str | None = None) -> list[str]:
        out: set[str] = set()
        for k in [key] if isinstance(key, str) else key or []:
            out |= self.lex.texts(k)
        if text:
            out.add(text.strip())
        if not out:
            raise ActionError(f"không có chữ cho key={key!r} text={text!r}")
        return sorted(out)

    def text_sel(self, key=None, text=None, prefix=False) -> dict:
        return {"textMatches": _rx(self.texts(key, text), prefix)}

    def row_sel(self, key=None, text=None, texts: list[str] | None = None) -> dict:
        """Dòng / nút bấm được mà mô tả bắt đầu bằng chữ (RN gộp nhãn con: "Khoá công tắc, Khoá trên thiết bị, ..")."""
        alts = "|".join(_jre(t) for t in (texts or self.texts(key, text)))
        return {"descriptionMatches": r"(?s)^\s*(?:" + alts + r")(?:,.*)?$", "clickable": True}

    def option_sel(self, key=None, text=None, texts: list[str] | None = None) -> dict:
        """Mục trong sheet / chip / ô ngày: mô tả ĐÚNG bằng chữ."""
        alts = "|".join(_jre(t) for t in (texts or self.texts(key, text)))
        return {"descriptionMatches": r"(?s)^\s*(?:" + alts + r")\s*$", "clickable": True}

    # ---- đọc nhiều phần tử: 1 lần dump (lặp d(...) = 1 RPC/phần tử → server uiautomator2 hay đứt) ----
    def elements(self) -> list[Element]:
        return parse(self.d.dump_hierarchy(), config.APP_PACKAGE)

    # ---- tìm / chờ ----
    def find(self, sel: dict, timeout: float = 0) -> tuple[int, int, int, int] | None:
        return U2.locate(sel) or (U2.wait(sel, timeout) if timeout else None)

    def need(self, sel: dict, what: str, timeout: float = WAIT) -> tuple[int, int, int, int]:
        b = self.find(sel, timeout)
        if b is None:
            raise ActionError(f"không thấy {what}")
        return b

    def reach(self, sel: dict, what: str) -> tuple[int, int, int, int]:
        """Đưa phần tử ở màn hiện tại vào vùng nhìn thấy. Màn có vùng cuộn (node.scroll) → scroll.reach của navigator
        và cộng độ cuộn vào pointer — route sau tap theo toạ độ đã học trừ độ cuộn này, cuộn mà không báo là trúng nhầm."""
        nav = self.s.nav
        n = self.s.graph.nodes.get(nav.cur)
        if not (n and n.scroll):
            return self.need(sel, what)
        if n.id not in nav.scroll:                       # chưa biết độ cuộn (vd tiến trình mới, trang để ở cuối)
            nav.to_top(n.id)
        r = _reach(sel, nav._area(n), spec_selector(n.scroll["ref"], self.lex), scroll=nav.scroll.get(n.id, 0))
        nav.scroll[n.id] = nav.scroll.get(n.id, 0) + r.scrolled
        if r.bounds is None:
            raise ActionError(f"không thấy {what} (kéo {r.drags} lần{', hết trang' if r.end else ''})")
        return r.bounds

    def settled(self, sel: dict, what: str, timeout: float = WAIT) -> tuple[int, int, int, int]:
        """Vị trí khi đã đứng yên (sheet đang trượt lên → toạ độ đọc giữa chừng sẽ tap trúng mục bên dưới)."""
        b = self.need(sel, what, timeout)
        end = time.monotonic() + 1.5
        while time.monotonic() < end:
            time.sleep(0.12)
            nb = U2.locate(sel)
            if nb == b:
                return b
            b = nb or b
        return b

    def gone(self, sel: dict, timeout: float = WAIT) -> bool:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if U2.locate(sel) is None:
                return True
            time.sleep(0.1)
        return False

    # ---- chạm ----
    def tap(self, b: tuple[int, int, int, int]) -> None:
        self.d.click((b[0] + b[2]) // 2, (b[1] + b[3]) // 2)

    def drag(self, x: int, y1: int, y2: int, hold: float = 0.3) -> None:
        """Kéo rồi đứng yên `hold` s trước khi nhả → không văng (bánh xe khớp nấc, danh sách dừng đúng chỗ).
        Dùng U2.drag (nhích qua ngưỡng chạm rồi nhảy thẳng tới đích, 4 RPC): ~0.7 s với hold 0.3, trước (8 bước) ~1.6 s.
        Đã thử bánh xe tuần hoàn +5 nấc: đúng nấc (bánh xe tự khớp nấc gần nhất, 30 px nhích không ảnh hưởng)."""
        U2.drag(x, y1, y2, hold=hold)

    def scroll_up(self, px: int) -> None:
        """Cuộn form lên `px` (nội dung đi lên), kéo ở cột trống bên phải."""
        y1 = 2300
        U2.drag(self.SCROLL_X, y1, max(320, y1 - px - U2.NUDGE))   # kéo nhanh không văng (~0.5 s)
        time.sleep(0.25)

    def reveal(self, sel: dict, what: str, floor: dict | None = None) -> tuple[int, int, int, int]:
        """Cuộn form tới khi phần tử hiện ra (nằm dưới màn thì cuộn dần) và nằm hẳn trên nút nổi `floor`
        (vd Lưu lại — tap trúng phần bị đè là bấm nút đó). Không tap. → khung phần tử."""
        b = self.find(sel, 1.0)
        for _ in range(3):
            if b:
                break
            self.scroll_up(700)
            b = self.find(sel, 0.5)
        if b is None:
            raise ActionError(f"không thấy {what}")
        f = U2.locate(floor) if floor else None
        if f and b[3] > f[1] - 10:
            self.scroll_up(b[3] - f[1] + 260)
            b = self.need(sel, what)
            f = U2.locate(floor)
            if f and b[3] > f[1] - 10:
                raise ActionError(f"{what} vẫn bị nút nổi đè sau khi cuộn")
        return b

    def tap_clear(self, sel: dict, what: str, floor: dict | None = None) -> None:
        self.tap(self.reveal(sel, what, floor))

    # ---- sheet ----
    def pick(self, key=None, text=None, texts: list[str] | None = None, what: str = "mục trong sheet") -> None:
        """Chọn một mục trong sheet đang mở rồi chờ sheet đóng."""
        sel = self.option_sel(key, text, texts)
        b = self.settled(sel, what)
        # Bấm phần chữ bên trái dòng, KHÔNG bấm tâm: sheet "Khoá công tắc" có nút ▼ () đè giữa mép dưới
        # danh sách, cách tâm dòng cuối "Không khoá" ~15 px → bấm tâm lúc trúng dòng, lúc trúng ▼ (sheet đứng im).
        self.d.click(b[0] + min(160, (b[2] - b[0]) // 4), (b[1] + b[3]) // 2)
        if not self.gone(sel):
            raise ActionError(f"chọn {what} xong sheet không đóng")
        time.sleep(0.3)

    def cancel_sheet(self) -> None:
        sel = self.option_sel(key="cancel")
        if U2.locate(sel):
            self.tap(U2.locate(sel))
            self.gone(sel)

    # ---- ô nhập ----
    def fill(self, value: str, index: int = 0) -> None:
        """Điền thẳng chữ vào ô nhập (accessibility set_text — như dán, không gõ phím) rồi ẩn bàn phím."""
        box = self.d(className="android.widget.EditText", instance=index)
        if not box.exists:
            raise ActionError("không thấy ô nhập")
        box.set_text(value)
        if box.get_text().strip() != value.strip():
            raise ActionError(f"ô nhập không nhận {value!r} (đang là {box.get_text()!r})")
        self.hide_keyboard()

    def hide_keyboard(self) -> None:
        if "mInputShown=true" in self.d.shell("dumpsys input_method").output:
            self.d.press("back")                 # Back khi bàn phím đang hiện chỉ đóng bàn phím
            time.sleep(0.4)

    # ---- danh sách chọn số (dialog native: "Chọn phút", "Chọn giây", "Phút"…) ----
    def pick_number(self, target: int, what: str) -> None:
        """Dialog mở khi bấm vào ô số: cuộn danh sách tới `target` rồi bấm (dialog tự đóng).
        Xa thì vuốt nhanh, gần thì kéo chậm đúng số dòng; bấm khi dòng hiện trọn."""
        num = {"className": "android.widget.Button", "textMatches": r"^\d+$"}
        self.need(num, f"danh sách chọn {what}")
        last = None
        for _ in range(60):
            rows = sorted((int(e.text), e.text, e.bounds) for e in self.elements()
                          if e.cls == "android.widget.Button" and e.text.strip().isdigit())
            h = max(b[3] - b[1] for _, _, b in rows)
            hit = next(((t, b) for v, t, b in rows if v == target and b[3] - b[1] >= h - 4), None)
            if hit:
                sel = {"className": "android.widget.Button", "text": hit[0]}
                if U2.locate(sel) != hit[1]:                 # còn trôi sau cú vuốt → bấm lúc này chỉ dừng cuộn
                    time.sleep(0.3)
                    continue
                self.tap(hit[1])
                if self.gone(sel, 1.5):
                    time.sleep(0.2)
                    return
                continue
            vals = [v for v, _, _ in rows]
            if vals == last and target not in vals:
                raise ActionError(f"{what}: không có {target} (danh sách dừng ở {vals[0]}–{vals[-1]})")
            last = vals
            x, top, bot = (rows[0][2][0] + rows[0][2][2]) // 2, rows[0][2][1], rows[-1][2][3]
            n = target - (vals[0] + vals[-1]) // 2           # số dòng cần dời để target về giữa
            if abs(n) > 40:                                  # xa: vuốt nhanh (văng), vòng sau đo lại
                y1, y2 = (bot - h, top + h) if n > 0 else (top + h, bot - h)
                self.d.swipe(x, y1, x, y2, 0.05)
                time.sleep(0.8)
            else:                                            # gần: kéo chậm đúng n dòng (kéo lên = số tăng)
                dist = max(-(bot - top - 2 * h), min(bot - top - 2 * h, n * h))
                y1 = bot - h if dist > 0 else top + h
                self.drag(x, y1, y1 - dist, hold=0.15)
                time.sleep(0.3)
        raise ActionError(f"không cuộn tới {target} trong danh sách chọn {what}")

    # ---- bánh xe số ----
    def wheels(self) -> list[tuple[int, int, int, int]]:
        """Các bánh xe số trên màn (View native bấm được, cao > 400 px), trái → phải."""
        return sorted(e.bounds for e in self.elements()
                      if e.cls == "android.view.View" and e.clickable and e.bounds[3] - e.bounds[1] > 400)

    def set_wheel(self, wheel: tuple[int, int, int, int], value: int) -> None:
        """Đặt bánh xe số không cần cuộn: bấm số đang chọn (giữa bánh xe) → hộp thoại "Nhập giá trị (0 - 59)" →
        điền thẳng → OK. Đúng cả khi không biết bánh xe đang ở đâu (form tuần hoàn giữ giá trị lần trước).

        Hộp thoại mở bằng JS: ngay sau lần đặt trước JS còn bận → có lúc mở trễ > 1 s. Bấm lại sớm = xếp thêm
        một lần mở → hộp thoại thừa bật lên sau khi đã xong (chặn các thao tác sau). Nên: bấm 1 lần, chờ tới 4 s;
        trước khi bấm thì Huỷ hộp thoại thừa nếu còn.
        Đo trên 2fc3878f: ~1.6–1.9 s/bánh xe (bấm · chờ hộp thoại ~0.5 · setText · click(selector) OK · wait_gone)."""
        box = self.d(className="android.widget.EditText")
        ok = self.d(className="android.widget.Button", **self.text_sel(key="ok", text="OK"))
        cancel = self.d(className="android.widget.Button", **self.text_sel(key="cancel", text="Huỷ"))
        if box.exists:                                   # hộp thoại mở trễ của lần bấm trước
            cancel.jsonrpc.click(cancel.selector)
            box.wait_gone(timeout=3.0)
        for _ in range(2):
            self.tap(wheel)
            if box.wait(timeout=4.0):
                break
        else:
            raise ActionError("bấm bánh xe 2 lần (chờ 4 s mỗi lần) nhưng không mở hộp thoại nhập giá trị")
        if not box.jsonrpc.setText(box.selector, str(value)):
            raise ActionError(f"ô nhập bánh xe không nhận {value}")
        if not ok.jsonrpc.click(ok.selector):
            raise ActionError("không bấm được nút OK của hộp thoại bánh xe")
        if not box.wait_gone(timeout=3.0):
            raise ActionError(f"đặt bánh xe {value} nhưng hộp thoại không đóng (ngoài khoảng cho phép?)")

    def turn(self, wheel: tuple[int, int, int, int], current: int, target: int, size: int) -> None:
        """Đưa bánh xe cuộn vòng từ `current` tới `target` (0..size-1), chọn chiều ngắn, tối đa 10 nấc/lần kéo."""
        step = (wheel[3] - wheel[1]) / 5
        delta = (target - current) % size
        if delta > size // 2:
            delta -= size
        x = (wheel[0] + wheel[2]) // 2
        up, down = wheel[3] - 40, wheel[1] + 40
        h = self.d.window_size()[1]
        max_up, max_down = min(10, int((up - 100) // step)), min(10, int((h - 100 - down) // step))  # ngón tay ở trong màn
        while delta:
            n = max(-max_down, min(max_up, delta))
            if n > 0:                                # lên = tăng
                self.drag(x, up, int(up - n * step))
            else:
                self.drag(x, down, int(down - n * step))
            delta -= n
            time.sleep(0.35)                         # chờ khớp nấc

    # ---- trạng thái bằng màu ----
    def green(self, boxes: list[tuple[int, int, int, int]]) -> list[bool]:
        """Mỗi khung có phải đang "chọn" (màu xanh của app) không — một ảnh chụp cho cả danh sách."""
        img = self.d.screenshot().convert("RGB")
        out = []
        for b in boxes:
            px = [img.getpixel((x, y)) for x in range(b[0] + 4, b[2] - 4, max(1, (b[2] - b[0]) // 8))
                  for y in range(b[1] + 4, b[3] - 4, max(1, (b[3] - b[1]) // 8))]
            out.append(sum(1 for r, g, bl in px if g > 140 and g > r + 50 and g > bl + 20) >= len(px) // 5)
        return out


def node(scout, prefix: str, device: str) -> str:
    """Id node của màn `prefix` (vd "timer/add", "infoDevice@") thuộc thiết bị tên `device` (bỏ khoảng trắng 2 đầu)."""
    for nid in scout.graph.nodes:
        if nid.startswith(prefix) and nid.endswith("]") and nid[nid.rindex("[") + 1:-1].strip() == device.strip():
            return nid
    raise ActionError(f"không có màn {prefix!r} của thiết bị {device!r}")


def arrive(scout, node_id: str) -> None:
    """Form/sheet không phải cạnh của graph → sau khi app tự quay về màn `node_id` thì đặt lại 📍 cho scout."""
    scout.nav.cur = node_id
