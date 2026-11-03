"""Cây UI (XML của uiautomator) → list[Element]."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

_BOUNDS = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")


@dataclass(slots=True)
class Element:
    """Một phần tử trong cây UI (không phải node của graph)."""
    idx: int                  # thứ tự duyệt = thứ tự vẽ
    parent: int | None
    text: str
    desc: str                 # content-desc; RN gộp nhãn các con: "Ổ cắm, Lost connection"
    cls: str
    bounds: tuple[int, int, int, int]
    clickable: bool
    scrollable: bool

    def center(self) -> tuple[int, int]:
        left, top, right, bottom = self.bounds
        return (left + right) // 2, (top + bottom) // 2


def parse(xml: str, package: str | None = None) -> list[Element]:
    """`package`: chỉ giữ cây con của app này (dump uiautomator2 có cả launcher, systemui)."""
    out: list[Element] = []

    def walk(node: ET.Element, parent: int | None) -> None:
        for child in node:
            if child.tag != "node":
                continue
            if package and child.get("package") not in (None, "", package):
                continue
            m = _BOUNDS.match(child.get("bounds", ""))
            e = Element(
                idx=len(out), parent=parent,
                text=child.get("text", ""), desc=child.get("content-desc", ""),
                cls=child.get("class", ""),
                bounds=tuple(map(int, m.groups())) if m else (0, 0, 0, 0),
                clickable=child.get("clickable") == "true",
                scrollable=child.get("scrollable") == "true",
            )
            out.append(e)
            walk(child, e.idx)

    walk(ET.fromstring(xml), None)
    return out
