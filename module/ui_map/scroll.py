"""Tìm phần tử trong màn có vùng cuộn mà không dump: hỏi trên máy, chưa thấy thì kéo từng nấc.

Vị trí trong nội dung: content_y = y_trên_màn + scroll. Biết content_y (học trong discovery) và
scroll hiện tại (pointer) thì kéo đúng một lần là tới; không biết thì dò từng nấc.
Độ cuộn đo bằng một phần tử mốc trước/sau mỗi lần kéo; mốc không dịch nữa = hết nội dung. Mốc lấy lại trước
mỗi lần kéo (dòng thấp nhất đang thấy) — mốc cố định ở đầu trang trôi khỏi màn ngay lần kéo đầu, khi đó không
biết đã chạm cuối, cứ kéo tới max_drags (đo: trang 853 px, tìm phần tử không có → kéo 8 lần, 7.8 s).
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from .. import interact as adb


@dataclass(slots=True)
class Area:
    """Vùng cuộn trên màn: chỉ phần tử nằm trọn trong [top, bottom] mới coi là chạm được."""
    top: int
    bottom: int
    x: int                    # cột để kéo (giữa màn, tránh nút ở mép)

    def inside(self, b: tuple[int, int, int, int]) -> bool:
        return b[1] >= self.top and b[3] <= self.bottom


@dataclass(slots=True)
class Reach:
    bounds: tuple[int, int, int, int] | None
    drags: int                # số lần kéo
    scrolled: int             # px đã cuộn thêm (đo bằng mốc)
    ms: int
    end: bool = False         # đã chạm cuối nội dung


SLOP = 30   # = interact.u2.NUDGE: đoạn nhích đầu mỗi lần kéo, nội dung không cuộn đoạn này


def _drag_by(area: Area, px: int) -> None:
    """Cuộn nội dung lên đúng px (tối đa chiều cao vùng − 80 − SLOP)."""
    start = area.bottom - 40
    adb.drag(area.x, start, max(area.top + 40, start - px - SLOP))


def _mark(area: Area, ref: dict, px: int) -> tuple[dict, int] | None:
    """Mốc đo lần kéo sắp tới: `ref` nếu kéo xong vẫn còn trên màn, không thì dòng thấp nhất đang thấy."""
    b = adb.locate(ref)
    if b and area.inside(b) and b[1] - px > area.top + 10:
        return ref, b[1]
    return adb.lowest(area.top, area.bottom)


def to_top(area: Area, ref: dict, ref_top: int, max_drags: int = 6, known: int | None = None) -> int:
    """Về đầu trang mà KHÔNG kéo quá đầu (kéo quá = pull-to-refresh: trang bị đẩy xuống + app tải lại → tap lệch).

    ref_top: y của mốc khi màn ở đầu trang (học trong discovery). Mốc đã ở đó → không kéo gì.
    Mốc thấy được → kéo đúng phần còn thiếu. Mốc khuất phía trên: biết độ cuộn (`known`, pointer navigator) → kéo đúng
    bấy nhiêu 1 lần; không biết → kéo 1/3 vùng mỗi lần rồi kiểm (trước kéo cứng nửa vùng ~1185 px trong khi trang chỉ
    cuộn 853 px → quá đầu → tải lại). → số lần kéo.
    """
    for n in range(max_drags + 1):
        b = adb.locate(ref)
        if b and b[1] >= ref_top - 3:
            return n
        if n == max_drags:
            break
        if b:
            need = ref_top - b[1]
        elif known:
            need, known = known, None                 # chỉ tin độ cuộn cho lần kéo đầu
        else:
            need = int((area.bottom - area.top) / 3)
        start = area.top + 40
        adb.drag(area.x, start, min(area.bottom - 40, start + need + SLOP))
    return max_drags


def reach(selector: dict, area: Area, ref: dict, *, content_y: int | None = None, scroll: int = 0,
          step: float = 0.5, max_drags: int = 8) -> Reach:
    """Đưa phần tử vào vùng nhìn thấy → khung thật của nó.

    ref: selector một phần tử luôn có trong nội dung cuộn, dùng làm mốc đo độ cuộn.
    content_y + scroll (từ pointer): kéo thẳng tới vị trí cần, rồi hỏi máy xác nhận.
    Không có: kéo từng nấc `step` × chiều cao vùng, hỏi sau mỗi nấc.
    """
    t0 = time.monotonic()
    done = lambda b, n, s, end=False: Reach(b, n, s, int((time.monotonic() - t0) * 1000), end)
    b = adb.locate(selector)
    if b and area.inside(b):
        return done(b, 0, 0)

    drags = scrolled = 0
    plan = [content_y - scroll - (area.top + area.bottom) // 2] if content_y is not None else []
    while drags < max_drags:
        planned = bool(plan)
        px = plan.pop(0) if plan else int((area.bottom - area.top) * step)
        if px <= 0:
            break
        mark = None if planned else _mark(area, ref, px)  # kéo theo vị trí đã học: đo bằng chính phần tử đích
        _drag_by(area, px)
        drags += 1
        b = adb.locate(selector)
        if mark:
            new = adb.locate(mark[0])
            moved = mark[1] - new[1] if new else px      # mất mốc (hiếm) → coi như cuộn đủ
        elif b:
            moved = content_y - b[1] - (scroll + scrolled)   # content_y = y trên màn + độ cuộn
        else:
            moved = px
        scrolled += moved
        if b and area.inside(b):
            return done(b, drags, scrolled)
        if mark and abs(moved) < 5:              # mốc không dịch → hết nội dung
            return done(None, drags, scrolled, end=True)
    return done(None, drags, scrolled)
