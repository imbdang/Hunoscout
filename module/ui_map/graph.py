"""Struct node/edge của map và tìm đường ngắn nhất."""
from __future__ import annotations

import heapq
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field


@dataclass(slots=True)
class Target:
    """Chạm vào ĐÂU — mô tả bằng selector, không bằng toạ độ."""
    desc: str | None = None    # content-desc (đã điền tham số)
    key: str | None = None     # i18n key → chữ ở mọi ngôn ngữ
    text: str | None = None    # chữ cố định
    glyph: str | None = None   # tên icon font, tra codepoint trong pattern
    match: str = "exact"       # exact | prefix | part | contains — áp cho desc
    after: str | None = None   # i18n key tiêu đề mục: chỉ tìm phần tử nằm dưới nó
    header: int | None = None  # nút thứ n (0 = trái, -1 = phải) của hàng nút trên cùng — icon SVG không chữ/desc/id


@dataclass(slots=True)
class Action:
    """LÀM GÌ."""
    gesture: str               # tap | hold | back
    target: Target | None = None
    ms: int = 800              # giữ cho hold. Đo 2026-11-03: 0.55 s và 0.8 s tới màn như nhau (~1.47 s, app chuyển màn từ mốc
                               # long press 500 ms) → giữ 0.8 s cho chắc không thành tap (= bật/tắt thiết bị)


@dataclass(slots=True)
class Edge:
    """Một cách chuyển từ màn `src` sang màn `to`."""
    id: str                    # "room>detailRoom[Nhà tắm]" — khoá của toạ độ đã lưu
    src: str
    to: str
    action: Action
    file: str                  # file pattern chứa cạnh: "core", "sswitch2v"...
    sig: str                   # hash định nghĩa cạnh: sửa pattern → toạ độ cũ mất hiệu lực
    back: bool = False         # sinh từ "@back": đích phụ thuộc màn đã đi vào
    cost_ms: int = 3000        # trọng số Dijkstra, cập nhật bằng thời gian đo được
    control: str | None = None # key của nút sinh ra cạnh này (vd "general_info")
    optional: bool = False     # nút có "when": lúc chạy có thể chưa/không hiện (vd dòng liên kết chờ thiết bị trả lời)


@dataclass(slots=True)
class Node:
    """Một màn hình (một instance: mỗi phòng/thiết bị là một node riêng)."""
    id: str                    # "home", "detailRoom[Nhà tắm]", "infoDevice@sswitch2v[Ổ cắm]"
    route: str                 # tên route trong code app
    file: str
    anchors: list[str | list[str]]  # i18n key bắt buộc có; một list con = chỉ cần một trong số đó
    anchor: dict | None = None      # selector chờ nhanh ngay trên máy sau mỗi bước, vd {"key": "roomManager"}
    check_text: str | None = None   # chữ bắt buộc có (vd tên phòng) — phân biệt các instance
    danger: list[str] = field(default_factory=list)  # thứ không được chạm, để agent đọc
    edges: list[Edge] = field(default_factory=list)
    controls: dict[str, dict] = field(default_factory=dict)  # key → nút (kind: nav/popup/action/danger/...)
    scroll: dict | None = None      # màn có vùng cuộn: {"ref": selector mốc đo độ cuộn}
    overlay: bool = False           # popup / sheet: đóng rồi thì không nằm trong đường quay lại

    @property
    def explored(self) -> bool:
        """Đã biết cách nhận ra màn này chưa (stub mới tạo thì chưa)."""
        return bool(self.anchors)


class Map:
    def __init__(self, nodes: list[Node]):
        self.nodes: dict[str, Node] = {n.id: n for n in nodes}

    def edges(self) -> Iterator[Edge]:
        for n in self.nodes.values():
            yield from n.edges

    def edge(self, edge_id: str) -> Edge:
        for e in self.edges():
            if e.id == edge_id:
                return e
        raise KeyError(edge_id)

    def path(self, src: str, dst: str, ok: Callable[[Edge], bool] = lambda e: True,
             cost: Callable[[Edge], float] = lambda e: e.cost_ms) -> list[Edge]:
        """Dijkstra theo `cost` (mặc định cost_ms), chỉ đi các cạnh `ok(edge)` cho phép."""
        if src == dst:
            return []
        dist, prev, pq = {src: 0}, {}, [(0, src)]
        while pq:
            d, u = heapq.heappop(pq)
            if u == dst:
                break
            if d > dist[u]:
                continue
            for e in self.nodes[u].edges:
                nd = d + cost(e)
                if ok(e) and nd < dist.get(e.to, float("inf")):
                    dist[e.to], prev[e.to] = nd, (u, e)
                    heapq.heappush(pq, (nd, e.to))
        if dst not in prev:
            raise LookupError(f"không có đường {src} → {dst}")
        out, v = [], dst
        while v != src:
            v, e = prev[v]
            out.append(e)
        return out[::-1]
