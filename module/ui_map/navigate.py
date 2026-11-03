"""Đi trên điện thoại theo Map: nhận diện màn, thực hiện cạnh, xác minh, lập lại đường khi lạc.

Pointer = (node hiện tại, độ cuộn từng màn, stack các màn đã đi vào) — luôn biết đang ở đâu,
in ra mỗi lần chuyển màn ("📍 ...").
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable

from .. import config
from .. import interact as adb
from .element import Element, parse
from .graph import Edge, Map, Node, Target
from .lexicon import Lexicon
from .locate import (Ambiguous, anchor_selector, anchor_texts, device_selectors, learns_band, locate,
                     anchor_selectors, satisfied, spec_selector, title_element, unique_selector)
from .resolved import Resolved
from .scroll import Area, reach, to_top

log = logging.getLogger(__name__)


class Lost(RuntimeError):
    """Không nhận ra màn / không thấy phần tử / không tới được đích."""


class Absent(RuntimeError):
    """Nút có điều kiện (cạnh optional) không hiện lúc chạy — vd thiết bị offline nên dòng liên kết
    không có. Không phải lạc: dừng luôn, không nhận diện lại / thử lại, không ghi cache."""


def _center(b: tuple[int, int, int, int]) -> tuple[int, int]:
    return (b[0] + b[2]) // 2, (b[1] + b[3]) // 2


class Navigator:
    SETTLE = 0.3       # giây chờ sau thao tác trước khi dump lần đầu (cách dump; anchors loại được màn cũ)
    WAIT = 12.0        # giây tối đa chờ màn đích hiện ra (cách dump)
    WAIT_ANCHOR = 3.0  # giây tối đa chờ title trên máy (cách nhanh)
    WAIT_OPTIONAL = 3.0  # giây chờ nút có điều kiện hiện ra (dòng liên kết hiện sau khi thiết bị trả lời)
    QUICK = True       # thử: thấy title màn đích là đi tiếp sau QUICK_DELAY, không chờ màn trượt xong (_settle)
    QUICK_DELAY = 0.1
    BLIND = False      # thử (tắt 2026-11-03: app chuyển màn ~0.4–0.6 s, tap mù 0.1 s rơi vào màn cũ): bước đã có toạ độ + bước kế tiếp cũng có → thao tác rồi đi tiếp, KHÔNG chờ màn đích
    BLIND_DELAY = 0.1
    BLIND_BACK_MS = 300  # chi phí lập đường của Back đã học khi BLIND_BACK (đo: back mù 0.26–0.33 s, có xác minh ~0.65 s)
    BLIND_BACK = True  # Back mà bước kế tiếp cũng là Back → bấm phím rồi đi tiếp, chỉ xác minh màn cuối chuỗi Back.
                       # Khác tap mù: phím Back Android xếp hàng gửi cho cửa sổ đang mở, không "rơi vào màn cũ".

    def __init__(self, graph: Map, resolved: Resolved, lex: Lexicon, glyphs: dict[str, str]):
        self.g, self.res, self.lex, self.glyphs = graph, resolved, lex, glyphs
        self.cur: str | None = None
        self.stack: list[str] = []               # các màn đã đi vào (đỉnh = màn mà Back sẽ về)
        self.scroll: dict[str, int] = {}         # node → px đã cuộn kể từ đầu trang
        self.came_from: dict[str, str] = {}      # node → màn đã đi vào nó (cho cạnh back)
        self._areas: dict[str, Area] = {}
        self._els: list[Element] | None = None   # cây UI hiện tại; None = đã thao tác, phải dump lại
        self.on_move: Callable[[Edge, str, int], None] | None = None   # gọi sau mỗi bước (trang web đo tốc độ)

    # ---- pointer ----

    def pointer(self) -> dict:
        return {"node": self.cur, "scroll": self.scroll.get(self.cur, 0), "stack": list(self.stack)}

    def _moved(self, edge: Edge, how: str, ms: int) -> None:
        if edge.back:
            if self.stack and self.stack[-1] == edge.to:
                self.stack.pop()
        elif self.g.nodes[edge.src].overlay:     # đóng popup → về màn bên dưới, không thêm vào stack
            pass
        else:
            self.stack.append(edge.src)
            self.came_from[edge.to] = edge.src
            self.scroll[edge.to] = 0             # RN mở màn mới ở đầu trang
        self.cur = edge.to
        log.info("📍 %-52s ← %-14s %5d ms  %s", self.cur, edge.control or edge.action.gesture, ms, how)
        if self.on_move:
            self.on_move(edge, how, ms)

    # ---- đọc màn ----

    def elements(self) -> list[Element]:
        if self._els is None:
            self._els = parse(adb.dump(), config.APP_PACKAGE)
        return self._els

    def where(self) -> str | None:
        """Nhận diện màn hiện tại (dump mới)."""
        self._els = None
        els = self.elements()
        hits = [n for n in self.g.nodes.values() if n.explored and satisfied(n, els, self.lex)]
        hits.sort(key=lambda n: n.check_text is None)   # instance có check_text cụ thể hơn
        self.cur = hits[0].id if hits else None
        if self.cur is None or (self.stack and self.stack[-1] == self.cur):
            self.stack = []
        return self.cur

    def recover(self) -> str | None:
        """Lạc thì thử nhận diện; không được thì Back một lần rồi thử lại."""
        if self.where() is None:
            adb.back()
            time.sleep(self.SETTLE)
            self.where()
        return self.cur

    def learn_anchor(self, node_id: str) -> dict | None:
        """Ghi vị trí title (và mốc cuộn) của node trên máy này — gọi khi chắc chắn đang ở node đó."""
        node = self.g.nodes[node_id]
        if node.scroll and self.res.scroll_ref_top(node) is None:
            b = adb.locate(spec_selector(node.scroll["ref"], self.lex)) if adb.locate else None
            if b:
                self.res.put_scroll_ref(node, b[1])
        if not learns_band(node):
            return None
        el = title_element(self.elements(), node, self.lex)
        if el is None:
            return None
        self.res.put_anchor(node, el.text.strip(), (el.bounds[1], el.bounds[3]))
        return self.res.get_anchor(node)

    # ---- vùng cuộn ----

    def _area(self, node: Node) -> Area:
        if node.id not in self._areas:
            b = adb.locate({"scrollable": True})
            w, h = adb.screen_size()
            self._areas[node.id] = Area(b[1], b[3], w // 2) if b else Area(300, h - 40, w // 2)
        return self._areas[node.id]

    def to_top(self, node_id: str) -> None:
        """Về đầu trang (độ cuộn = 0). Chạy cả khi chưa biết độ cuộn (tiến trình mới, vào lại bằng Back): mốc đã ở
        chỗ đầu trang thì chỉ tốn 1 lần hỏi máy."""
        node = self.g.nodes[node_id]
        top = self.res.scroll_ref_top(node)
        if node.scroll and top is not None and self.scroll.get(node_id) != 0:
            to_top(self._area(node), spec_selector(node.scroll["ref"], self.lex), top)
            self.scroll[node_id] = 0

    # ---- thực hiện một cạnh ----

    def _find(self, edge: Edge, rec: dict | None) -> tuple[tuple[int, int], int | None, str]:
        """Toạ độ để chạm → (xy, content_y nếu nằm trong vùng cuộn, cách tìm)."""
        src, t = self.g.nodes[edge.src], edge.action.target
        # Toạ độ đã học (cả thẻ phòng, ô thiết bị): tap/hold thẳng. Ô đổi chỗ (thêm/xoá thiết bị) → kiểm tên ở
        # màn đích sai → run_edge xoá toạ độ này, lần thử lại hỏi máy và học lại.
        if rec and rec.get("xy") and "content_y" not in rec:
            return tuple(rec["xy"]), None, "cache"
        if src.scroll and adb.locate and (src.id not in self.scroll or rec and "content_y" in rec
                                          and rec["content_y"] - self.scroll[src.id] < self._area(src).top):
            # độ cuộn chưa biết (tiến trình mới, Back về trang đã cuộn) hoặc nút nằm phía trên khung đang thấy
            # (reach chỉ cuộn xuống) → về đầu trang trước, độ cuộn = 0 rồi mới tính toạ độ
            self.to_top(src.id)
        if rec and rec.get("xy") and "content_y" in rec and src.scroll and src.id in self.scroll:
            # Trong vùng cuộn: biết độ cuộn hiện tại (pointer) → vị trí trên màn = content_y − cuộn + dy.
            # Bản ghi cũ chưa có dy: chỉ tin khi lúc học trang ở đầu (0 ≤ tâm − content_y ≤ 150).
            dy = rec.get("dy", rec["xy"][1] - rec["content_y"])
            y = rec["content_y"] - self.scroll[src.id] + dy
            area = self._area(src)
            if 0 <= dy <= 150 and area.top + dy <= y <= area.bottom - dy:
                return (rec["xy"][0], y), rec["content_y"], "cache (cuộn)"
        sels = device_selectors(t, self.lex, self.glyphs) if adb.locate else []
        for attempt in range(2):
            for sel in sels:
                if src.scroll:
                    area = self._area(src)
                    r = reach(sel, area, spec_selector(src.scroll["ref"], self.lex),
                              content_y=rec.get("content_y") if rec else None, scroll=self.scroll.get(src.id, 0))
                    self.scroll[src.id] = self.scroll.get(src.id, 0) + r.scrolled   # cả khi không thấy: trang đã cuộn
                    if r.bounds:
                        how = ("về đầu trang, " if attempt else "") + (f"cuộn {r.drags} lần" if r.drags else "hỏi máy")
                        return _center(r.bounds), r.bounds[1] + self.scroll[src.id], how
                elif b := adb.locate(sel):
                    return _center(b), None, "hỏi máy"
            if not (sels and src.scroll and self.scroll.get(src.id)):
                break
            self.to_top(src.id)                  # cuộn xuống từ giữa trang không thấy → có thể nằm phía trên
        if not sels:                                        # target cần lọc theo cây (after) → dump
            el = locate(self.elements(), t, self.glyphs, self.lex)
            if el:
                return el.center(), None, "dump"
        raise Lost(f"không thấy {t} trên {src.id}")

    def _cached(self, edge: Edge) -> bool:
        """Cạnh làm được mà không cần đọc màn: Back, hoặc toạ độ đã học ngoài vùng cuộn."""
        rec = self.res.get(edge)
        return rec is not None and not edge.optional and (
            edge.action.gesture == "back" or bool(rec.get("xy")) and "content_y" not in rec)

    def run_edge(self, edge: Edge, blind: bool = False) -> int:
        """Một bước: tìm nút → chạm → chờ màn đích. Cạnh chưa học thì học luôn (ghi toạ độ, title).

        Màn đích đã học vị trí title → chờ title đúng vị trí ngay trên máy (~0.2 s).
        Chưa học, hoặc title đích trùng chữ đang có ở màn nguồn → xác minh bằng dump + anchors.
        """
        t0 = time.monotonic()
        src, dst = self.g.nodes[edge.src], self.g.nodes[edge.to]
        rec = self.res.get(edge)
        if blind and self._cached(edge):         # chế độ mù: không chờ màn đích (goto quyết khi nào được mù)
            self._act(edge, None if edge.action.gesture == "back" else tuple(rec["xy"]))
            t1 = time.monotonic()
            time.sleep(self.BLIND_DELAY)
            ms = int((time.monotonic() - t0) * 1000)
            self._moved(edge, f"mù | {edge.action.gesture} {t1 - t0:.2f} · nghỉ {self.BLIND_DELAY:.2f}s", ms)
            return ms
        if edge.optional and not self._present(edge, rec):
            raise Absent(f"{edge.control}: {self.WAIT_OPTIONAL:.0f}s không hiện trên {src.id} "
                         "(chưa liên kết / thiết bị offline?)")
        try:
            xy, content_y, how = (None, None, "back") if edge.action.gesture == "back" else self._find(edge, rec)
        except Lost as err:
            if edge.optional:                    # dò hết trang không thấy → nút không có, không phải lạc
                raise Absent(f"{edge.control}: không có trên {src.id} ({err})") from err
            raise
        t1 = time.monotonic()                    # xong tìm nút
        self._act(edge, xy)
        t2 = time.monotonic()                    # xong thao tác
        try:
            seen, verify = self._verify(edge, src, dst)
        except Lost:
            if rec and how.startswith("cache"):  # toạ độ đã học không còn đúng (ô đổi chỗ...) → bỏ, lần sau hỏi máy
                self.res.forget(edge)
            raise
        t4 = time.monotonic()
        seen = seen or t4
        ms = int((t4 - t0) * 1000)
        if rec is None:
            dy = xy[1] - (content_y - self.scroll.get(src.id, 0)) if content_y is not None and xy else None
            self.res.put(edge, xy, ms, content_y, dy)
            how += ", học cạnh"
        if learns_band(dst) and self.res.get_anchor(dst) is None and self.learn_anchor(dst.id):
            how += " + title"
        how += (f" | tìm {t1 - t0:.2f} · {edge.action.gesture} {t2 - t1:.2f} · chờ màn {seen - t2:.2f}"
                f" · yên {t4 - seen:.2f}s ({verify})")
        self._moved(edge, how, ms)
        return ms

    def _verify(self, edge: Edge, src: Node, dst: Node) -> tuple[float | None, str]:
        """Sau thao tác: chờ tới khi chắc đang ở màn đích → (lúc thấy màn, cách xác minh). Không thấy → Lost."""
        band = (self.res.get_anchor(dst) or {}).get("band")
        clash = bool(anchor_texts(dst, self.lex) & (anchor_texts(src, self.lex) | {src.check_text}))
        sel = anchor_selector(dst, self.lex, self.glyphs)
        seen = None                              # lúc thấy màn đích (chưa chờ đứng yên)
        if band and not clash and adb.wait_band:
            b = adb.wait_band(sel, band, self.WAIT_ANCHOR)
            if b is None:
                raise Lost(f"{edge.id}: {self.WAIT_ANCHOR}s không thấy title của {dst.id}")
            seen, verify = time.monotonic(), "title"
            time.sleep(self.QUICK_DELAY) if self.QUICK else self._settle(sel, b, band)
            # Title chung cho mọi instance (vd "Chi tiết thiết bị") → phải thấy cả tên riêng, không thì vào nhầm.
            # Title chỉ có thể là chính cái tên đó (vd tên phòng ở detailRoom) → đã kiểm qua title, bỏ qua.
            name = (device_selectors(Target(text=dst.check_text), self.lex, self.glyphs)[0]
                    if dst.check_text and anchor_texts(dst, self.lex) - {dst.check_text.strip()} else None)
            # Back: màn quay về đã biết (chồng màn đã đi) → không cần kiểm tên, đỡ 1 lần hỏi máy (~0.3 s)
            if name and not edge.back and not (adb.locate(name) or adb.wait(name, 1.0)):
                raise Lost(f"{edge.id}: title đúng nhưng không thấy {dst.check_text!r} — vào nhầm màn cùng loại")
        elif (not learns_band(dst) and not clash and sel and adb.wait
              and (b := adb.wait(sel, self.WAIT_ANCHOR))):
            # Title không cố định vị trí (vd Home): thấy chữ chỉ màn đích có là đủ — không ngủ cứng + dump
            seen, verify = time.monotonic(), "chữ"
            time.sleep(self.QUICK_DELAY) if self.QUICK else self._settle(sel, b, None)
        elif (adb.wait and (uniq := unique_selector(src, dst, self.lex))
              and (adb.locate(uniq) or adb.wait(uniq, self.WAIT_ANCHOR))):
            # Title trùng màn nguồn / chưa học vị trí: chữ chỉ màn đích có (vd "Danh sách người được chia sẻ")
            seen, verify = time.monotonic(), "chữ riêng"
            time.sleep(self.QUICK_DELAY)
        elif adb.locate and self._wait_anchors(dst):
            seen, verify = time.monotonic(), "đủ anchors"
            time.sleep(self.QUICK_DELAY)
        else:
            raise Lost(f"{edge.id}: không thấy màn {dst.id}")
        return seen, verify

    def _present(self, edge: Edge, rec: dict | None) -> bool:
        """Cạnh optional: chờ nút hiện ra tại chỗ, KHÔNG cuộn. False = không hiện.

        Chỉ khi vị trí đã học nằm dưới khung đang nhìn mới cho cuộn tiếp (_find/reach), vì khi đó
        chưa cuộn tới thì chưa biết có hay không.
        """
        sels = device_selectors(edge.action.target, self.lex, self.glyphs) if adb.wait else []
        if not sels:
            return True                          # không hỏi máy được → để _find xử lý như thường
        if adb.wait(sels[0], self.WAIT_OPTIONAL):
            return True
        src = self.g.nodes[edge.src]
        cy = rec.get("content_y") if rec else None
        return bool(src.scroll) and cy is not None and cy - self.scroll.get(src.id, 0) > self._area(src).bottom

    def step(self, edge: Edge, verify: bool = True) -> tuple[bool, tuple[int, int] | None, int]:
        """Bước kiểu dump (discovery hàng loạt): → (tới đúng màn, toạ độ đã chạm, ms)."""
        t0 = time.monotonic()
        xy = None
        if edge.action.gesture != "back":
            xy = self._find(edge, self.res.get(edge))[0]
        self._act(edge, xy)
        ok = self._wait_for(edge.to) if verify else (time.sleep(self.SETTLE) or True)
        ms = int((time.monotonic() - t0) * 1000)
        if ok:
            self._moved(edge, "dump", ms)
        return ok, xy, ms

    def _act(self, edge: Edge, xy: tuple[int, int] | None) -> None:
        self._els = None
        g = edge.action.gesture
        if g == "back":
            adb.back()
        elif g == "tap":
            adb.tap(*xy)
        elif g == "hold":
            adb.hold(*xy, edge.action.ms)
        else:
            raise ValueError(f"gesture không hỗ trợ: {g!r}")

    def _wait_anchors(self, node: Node) -> bool:
        """Chờ đủ tổ hợp chữ của màn đích (mỗi nhóm anchor + tên riêng) — hỏi máy, KHÔNG dump cả màn."""
        sels = anchor_selectors(node, self.lex)
        end = time.monotonic() + self.WAIT
        while sels:
            if all(adb.locate(s) for s in sels):
                return True
            if time.monotonic() > end:
                return False
            time.sleep(0.1)
        return False

    def _wait_for(self, node_id: str) -> bool:
        node = self.g.nodes[node_id]
        end = time.monotonic() + self.WAIT
        time.sleep(self.SETTLE)
        while True:
            self._els = None
            if satisfied(node, self.elements(), self.lex):
                return True
            if time.monotonic() > end:
                return False
            time.sleep(0.5)

    def _settle(self, sel: dict, b: tuple, band: list | None, limit: float = 1.0) -> None:
        """Title đã có nhưng màn có thể còn đang trượt vào: chờ tới khi vị trí title đứng yên."""
        end = time.monotonic() + limit
        while time.monotonic() < end:
            nb = adb.wait_band(sel, band, 0.3) if band else adb.find(sel)
            if nb == b:
                return
            b = nb

    def _cost(self, e: Edge) -> float:
        """Back đã đi thành công (đã học) rẻ như back mù → lập đường ưu tiên nối chuỗi Back thay vì tap
        (vd detailRoom → Quản lý phòng). Back chưa học giữ chi phí cũ: không vì rẻ mà chọn Back chưa thử."""
        if self.BLIND_BACK and e.action.gesture == "back" and self.res.get(e) is not None:
            return min(e.cost_ms, self.BLIND_BACK_MS)
        return e.cost_ms

    def _back_ok(self, e: Edge) -> bool:
        return not e.back or self.came_from.get(e.src, e.to) == e.to

    # ---- đi tới đích ----

    def goto(self, dst: str, usable: Callable[[Edge], bool]) -> str:
        """Đi tới `dst` theo đường ngắn nhất qua các cạnh `usable` (đã học hoặc chưa — chưa thì học dọc đường).
        Lạc thì nhận diện lại rồi lập lại đường (tối đa 3 lần)."""
        if dst not in self.g.nodes:
            raise KeyError(f"không có node {dst!r}")
        for _ in range(3):
            if self.cur is None and self.recover() is None:
                raise Lost("không nhận ra màn hiện tại")
            if self.cur == dst:
                return dst
            path = self.g.path(self.cur, dst, ok=lambda e: usable(e) and self._back_ok(e), cost=self._cost)
            try:
                for i, e in enumerate(path):
                    # mù chỉ khi bước kế tiếp cũng làm được không cần đọc màn; bước cuối luôn xác minh
                    nxt = path[i + 1] if i + 1 < len(path) else None
                    self.run_edge(e, blind=nxt is not None and (
                        self.BLIND and self._cached(nxt)
                        or self.BLIND_BACK and e.action.gesture == "back" and nxt.action.gesture == "back"))
                return dst
            except (Lost, Ambiguous) as err:
                log.warning("lạc: %s → nhận diện lại, lập lại đường", err)
                self.cur = None
        raise Lost(f"không tới được {dst}")

    def scan_tiles(self, edges: list[Edge]) -> list[str]:
        """Đang ở màn chứa các ô (vd detailRoom): đọc màn MỘT lần, ghi toạ độ mới cho từng cạnh hold vào ô.

        Ô không thấy (thiết bị bị ẩn/cuộn khuất) → bỏ toạ độ cũ, lần route sau tìm theo tên.
        """
        self._els = None
        els = self.elements()
        done = []
        for e in edges:
            try:
                el = locate(els, e.action.target, self.glyphs, self.lex)
            except Ambiguous:
                el = None
            if el is None:
                self.res.forget(e)
                continue
            old = self.res.get(e)
            self.res.put(e, el.center(), old["cost_ms"] if old else e.cost_ms)
            done.append(e.id)
        log.info("quét ô thiết bị trên %s: %d/%d", self.cur, len(done), len(edges))
        return done

    # ---- discovery hàng loạt (cạnh core lúc khởi động) ----

    def discover(self, missing: Iterable[Edge]) -> tuple[list[Edge], list[tuple[Edge, str]]]:
        """Đi thử từng cạnh còn thiếu, ghi toạ độ + thời gian. Chọn cạnh gần màn hiện tại nhất trước."""
        todo = {e.id: e for e in missing}
        tries: dict[str, int] = {}
        done: list[Edge] = []
        failed: list[tuple[Edge, str]] = []
        known = lambda e: self.res.get(e) is not None
        while todo:
            if self.cur is None and self.recover() is None:
                failed += [(e, "lạc: không nhận ra màn hiện tại") for e in todo.values()]
                break
            pick = self._nearest(todo.values(), known)
            if pick is None:
                failed += [(e, "không có đường đã biết tới màn xuất phát") for e in todo.values()]
                break
            e, path = pick
            try:
                for x in path:
                    self.run_edge(x)
                self.run_edge(e)
            except (Lost, Ambiguous) as err:
                tries[e.id] = tries.get(e.id, 0) + 1
                log.warning("%s: %s", e.id, err)
                self.cur = None
                if tries[e.id] >= 2:
                    failed.append((e, str(err)))
                    del todo[e.id]
                continue
            del todo[e.id]
            done.append(e)
        return done, failed

    def _nearest(self, edges: Iterable[Edge], known: Callable[[Edge], bool]):
        best = None
        for e in edges:
            if e.src == self.cur:
                return e, []
            try:
                p = self.g.path(self.cur, e.src, ok=lambda x: known(x) and self._back_ok(x))
            except LookupError:
                continue
            cost = sum(x.cost_ms for x in p)
            if best is None or cost < best[0]:
                best = (cost, e, p)
        return (best[1], best[2]) if best else None
