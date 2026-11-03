"""Toạ độ đã phát hiện của một điện thoại: data/<serial>/huno_pattern/<file>.json.

Chỉ lưu phần bổ sung theo id cạnh, không chép lại pattern. Mỗi file ghi rõ được resolve trong
điều kiện nào (màn, density, cỡ chữ, bản app); điều kiện đổi thì toàn bộ toạ độ trong file bỏ.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from .graph import Edge, Map, Node

log = logging.getLogger(__name__)


def _anchor_sig(node: Node) -> str:
    return hashlib.sha1(json.dumps(node.anchor, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:10]


def resolved_for(profile: dict) -> dict:
    s = profile["screen"]
    return {"w": s["w"], "h": s["h"], "density": s["density"], "font_scale": s["font_scale"],
            "app": profile["app"]["version"]}


class Resolved:
    def __init__(self, directory: Path, profile: dict):
        self.dir = directory
        self.want = resolved_for(profile)
        self.files: dict[str, dict] = {}         # "core", "root_type/sswitch2v", "feature/timer" → doc
        for p in sorted(directory.rglob("*.json")):
            key = p.relative_to(directory).with_suffix("").as_posix()
            doc = json.loads(p.read_text(encoding="utf-8"))
            if doc.get("resolved_for") != self.want:
                log.warning("%s resolve cho %s, máy hiện tại %s → bỏ toạ độ cũ",
                            key, doc.get("resolved_for"), self.want)
                continue
            self.files[key] = doc

    def get(self, edge: Edge) -> dict | None:
        """Bản ghi hợp lệ của cạnh (cùng sig với pattern hiện tại), hoặc None."""
        rec = self.files.get(edge.file, {}).get("edges", {}).get(edge.id)
        return rec if rec and rec.get("sig") == edge.sig else None

    def put(self, edge: Edge, xy: tuple[int, int] | None, cost_ms: int, content_y: int | None = None) -> None:
        """Ghi một cạnh và lưu file ngay (discovery bị ngắt thì không mất phần đã làm).

        content_y: nút nằm trong vùng cuộn → vị trí trong nội dung (y trên màn + độ cuộn lúc đo);
        khi đó xy chỉ đúng ở độ cuộn đã đo, lúc chạy phải dùng reach() + content_y.
        """
        doc = self.files.setdefault(edge.file, {"resolved_for": self.want, "edges": {}})
        doc["edges"][edge.id] = {
            "xy": list(xy) if xy else None,
            **({"content_y": content_y} if content_y is not None else {}),
            "cost_ms": cost_ms,
            "sig": edge.sig,
            "verified": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        edge.cost_ms = cost_ms
        self._save(edge.file)

    def get_anchor(self, node: Node) -> dict | None:
        """Anchor đã học của node: {"text", "band": [top, bottom]}, hoặc None nếu chưa học / pattern đổi."""
        rec = self.files.get(node.file, {}).get("nodes", {}).get(node.id)
        return rec if rec and rec.get("sig") == _anchor_sig(node) else None

    def put_anchor(self, node: Node, text: str, band: tuple[int, int]) -> None:
        doc = self.files.setdefault(node.file, {"resolved_for": self.want, "edges": {}})
        doc.setdefault("nodes", {})[node.id] = {
            "text": text,
            "band": list(band),
            "sig": _anchor_sig(node),
            "verified": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        self._save(node.file)

    def apply_costs(self, graph: Map) -> None:
        """Đưa thời gian đo được vào trọng số của graph."""
        for e in graph.edges():
            rec = self.get(e)
            if rec:
                e.cost_ms = rec["cost_ms"]

    def prune(self, graph: Map) -> list[str]:
        """Bỏ bản ghi của cạnh / node không còn trong graph (thiết bị, phòng đổi tên hay bị xoá...)."""
        live = {e.id for e in graph.edges()} | set(graph.nodes)
        gone = []
        for file, doc in self.files.items():
            dead = []
            for section in ("edges", "nodes", "scroll"):
                part = doc.get(section, {})
                for i in [i for i in part if i not in live]:
                    del part[i]
                    dead.append(i)
            if dead:
                gone += dead
                self._save(file)
        return gone

    def put_scroll_ref(self, node: Node, ref_top: int) -> None:
        """y của mốc cuộn khi màn ở đầu trang (to_top dùng để về đầu mà không kéo quá → refresh)."""
        doc = self.files.setdefault(node.file, {"resolved_for": self.want, "edges": {}})
        doc.setdefault("scroll", {})[node.id] = ref_top
        self._save(node.file)

    def scroll_ref_top(self, node: Node) -> int | None:
        return self.files.get(node.file, {}).get("scroll", {}).get(node.id)

    def _save(self, file: str) -> None:
        path = self.dir / f"{file}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.files[file], ensure_ascii=False, indent=2), encoding="utf-8")
