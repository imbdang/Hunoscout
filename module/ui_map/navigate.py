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
from .graph import Edge, Map, Node
from .lexicon import Lexicon
from .locate import (Ambiguous, anchor_selector, anchor_texts, device_selectors, learns_band, locate,
                     satisfied, spec_selector, title_element)
from .resolved import Resolved
from .scroll import Area, reach, to_top

log = logging.getLogger(__name__)


class Lost(RuntimeError):
    """Không nhận ra màn / không thấy phần tử / không tới được đích."""


def _center(b: tuple[int, int, int, int]) -> tuple[int, int]:
    return (b[0] + b[2]) // 2, (b[1] + b[3]) // 2


class Navigator:
    SETTLE = 1.0       # giây chờ sau thao tác trước khi đọc màn (cách dump)
    WAIT = 12.0        # giây tối đa chờ màn đích hiện ra (cách dump)
    WAIT_ANCHOR = 3.0  # giây tối đa chờ title trên máy (cách nhanh)

    def __init__(self, graph: Map, resolved: Resolved, lex: Lexicon, glyphs: dict[str, str]):
        self.g, self.res, self.lex, self.glyphs = graph, resolved, lex, glyphs
        self.cur: str | None = None
        self.stack: list[str] = []               # các màn đã đi vào (đỉnh = màn mà Back sẽ về)
        self.scroll: dict[str, int] = {}         # node → px đã cuộn kể từ đầu trang
        self.came_from: dict[str, str] = {}      # node → màn đã đi vào nó (cho cạnh back)
        self._areas: dict[str, Area] = {}
        self._els: list[Element] | None = None   # cây UI hiện tại; None = đã thao tác, phải dump lại

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
        node = self.g.nodes[node_id]
        top = self.res.scroll_ref_top(node)
        if node.scroll and top is not None and self.scroll.get(node_id):
            to_top(self._area(node), spec_selector(node.scroll["ref"], self.lex), top)
            self.scroll[node_id] = 0

    # ---- thực hiện một cạnh ----

    def _find(self, edge: Edge, rec: dict | None) -> tuple[tuple[int, int], int | None, str]:
        """Toạ độ để chạm → (xy, content_y nếu nằm trong vùng cuộn, cách tìm)."""
        src, t = self.g.nodes[edge.src], edge.action.target
        if rec and rec.get("xy") and "content_y" not in rec:
            return tuple(rec["xy"]), None, "cache"
        sels = device_selectors(t, self.lex, self.glyphs) if adb.locate else []
        for sel in sels:
            if src.scroll:
                area = self._area(src)
                r = reach(sel, area, spec_selector(src.scroll["ref"], self.lex),
                          content_y=rec.get("content_y") if rec else None, scroll=self.scroll.get(src.id, 0))
                if r.bounds:
                    self.scroll[src.id] = self.scroll.get(src.id, 0) + r.scrolled
                    how = f"cuộn {r.drags} lần" if r.drags else "hỏi máy"
                    return _center(r.bounds), r.bounds[1] + self.scroll[src.id], how
            elif b := adb.locate(sel):
                return _center(b), None, "hỏi máy"
        if not sels:                                        # target cần lọc theo cây (after) → dump
            el = locate(self.elements(), t, self.glyphs, self.lex)
            if el:
                return el.center(), None, "dump"
        raise Lost(f"không thấy {t} trên {src.id}")

    def run_edge(self, edge: Edge) -> int:
        """Một bước: tìm nút → chạm → chờ màn đích. Cạnh chưa học thì học luôn (ghi toạ độ, title).

        Màn đích đã học vị trí title → chờ title đúng vị trí ngay trên máy (~0.2 s).
        Chưa học, hoặc title đích trùng chữ đang có ở màn nguồn → xác minh bằng dump + anchors.
        """
        t0 = time.monotonic()
        src, dst = self.g.nodes[edge.src], self.g.nodes[edge.to]
        rec = self.res.get(edge)
        xy, content_y, how = (None, None, "back") if edge.action.gesture == "back" else self._find(edge, rec)
        band = (self.res.get_anchor(dst) or {}).get("band")
        clash = bool(anchor_texts(dst, self.lex) & (anchor_texts(src, self.lex) | {src.check_text}))
        self._act(edge, xy)
        if band and not clash and adb.wait_band:
            sel = anchor_selector(dst, self.lex, self.glyphs)
            b = adb.wait_band(sel, band, self.WAIT_ANCHOR)
            if b is None:
                raise Lost(f"{edge.id}: {self.WAIT_ANCHOR}s không thấy title của {dst.id}")
            self._settle(sel, b, band)
        elif not self._wait_for(dst.id):
            raise Lost(f"{edge.id}: không thấy màn {dst.id}")
        ms = int((time.monotonic() - t0) * 1000)
        if rec is None:
            self.res.put(edge, xy, ms, content_y)
            how += ", học cạnh"
            if learns_band(dst) and self.res.get_anchor(dst) is None and self.learn_anchor(dst.id):
                how += " + title"
        self._moved(edge, how, ms)
        return ms

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
            path = self.g.path(self.cur, dst, ok=lambda e: usable(e) and self._back_ok(e))
            try:
                for e in path:
                    self.run_edge(e)
                return dst
            except (Lost, Ambiguous) as err:
                log.warning("lạc: %s → nhận diện lại, lập lại đường", err)
                self.cur = None
        raise Lost(f"không tới được {dst}")

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
