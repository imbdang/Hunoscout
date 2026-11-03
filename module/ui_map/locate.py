"""So cây UI với pattern: màn này có phải node X không, phần tử của Target nằm ở đâu."""
from __future__ import annotations

from .element import Element
from .graph import Node, Target
from .lexicon import Lexicon


class Ambiguous(LookupError):
    """Selector khớp nhiều phần tử bấm được — không đoán, dừng lại."""


def satisfied(node: Node, elements: list[Element], lex: Lexicon) -> bool:
    """Màn hiện tại có đủ anchors (+ check_text) của node không.

    check_text chỉ tính chữ không nằm trong phần tử bấm được (tiêu đề), vì cùng tên còn
    xuất hiện trên nút/chip — vd chip chọn phòng ở detailRoom.
    """
    texts = {e.text.strip() for e in elements if e.text}
    for anchor in node.anchors:
        keys = anchor if isinstance(anchor, list) else [anchor]
        if not any(lex.texts(k) & texts for k in keys):
            return False
    if node.check_text is None:
        return True
    return any(e.text.strip() == node.check_text and _clickable(elements, e) is None for e in elements)


def _desc_match(desc: str, want: str, mode: str) -> bool:
    if mode == "exact":
        return desc == want
    if mode == "prefix":                  # desc RN gộp nhãn con bằng ", "
        return desc == want or desc.startswith(want + ", ")
    if mode == "part":                    # "<icon>, 55%, Cảm biến nhiệt độ, 69% | 29°C"
        return want in (p.strip() for p in desc.split(", "))
    if mode == "contains":
        return want in desc
    raise ValueError(f"match không hỗ trợ: {mode!r}")


def _below(elements: list[Element], key: str, lex: Lexicon) -> int:
    """Mép dưới của tiêu đề mục `key`; 0 nếu tiêu đề không trên màn (đã cuộn qua → không lọc)."""
    want = lex.texts(key)
    tops = [e.bounds[3] for e in elements if e.text.strip() in want]
    return min(tops) if tops else 0


def _clickable(elements: list[Element], e: Element | None) -> Element | None:
    while e is not None and not e.clickable:
        e = elements[e.parent] if e.parent is not None else None
    return e


_JAVA_META = set(r"\.[]{}()*+?^$|")


def _jre(s: str) -> str:
    return "".join("\\" + c if c in _JAVA_META else c for c in s)


def anchor_texts(node: Node, lex: Lexicon) -> set[str]:
    """Các chữ có thể là title của node.

    {"key": i18n | [i18n...]} → mọi ngôn ngữ; {"text": "..."} → đúng chữ đó;
    {"any": [spec, ...]} → hợp của các spec (vd Home: title cuộn mất thì dùng tiêu đề mục).
    """
    a = node.anchor or ({"key": node.anchors[0]} if node.anchors else None)
    return _spec_texts(a, lex) if a else set()


def _spec_texts(a: dict, lex: Lexicon) -> set[str]:
    if "any" in a:
        return set().union(*(_spec_texts(s, lex) for s in a["any"]))
    if "key" in a:
        keys = a["key"] if isinstance(a["key"], list) else [a["key"]]
        return {t for k in keys for t in lex.texts(k)}
    if "text" in a:
        return {a["text"].strip()}
    raise ValueError(f"anchor không hỗ trợ: {a}")


def learns_band(node: Node) -> bool:
    """Title cố định (header) → học vị trí. "band": false khi title cuộn theo nội dung."""
    return bool(node.anchor) and node.anchor.get("band", True)


def anchor_selector(node: Node, lex: Lexicon, glyphs: dict[str, str]) -> dict | None:
    """Anchor (title) của node → selector uiautomator2 chạy trên máy.

    Selector chỉ so chữ. Vị trí title (dải y) học trong discovery, kiểm bằng wait_band —
    nhờ vậy phân biệt được title "Nhà tắm" với chip "Nhà tắm" trên màn phòng khác.
    """
    alts = anchor_texts(node, lex)
    if not alts:
        return None
    return {"textMatches": r"^\s*(" + "|".join(_jre(t) for t in sorted(alts)) + r")\s*$"}


def title_element(elements: list[Element], node: Node, lex: Lexicon) -> Element | None:
    """Phần tử title của node trên màn hiện tại: khớp chữ anchor, ưu tiên chữ không nằm trong
    phần tử bấm được (không phải chip/nút), rồi đến phần tử cao nhất."""
    want = anchor_texts(node, lex)
    hits = [e for e in elements if e.text.strip() in want]
    if not hits:
        return None
    return min(hits, key=lambda e: (_clickable(elements, e) is not None, e.bounds[1]))


def target_selectors(target: Target, glyphs: dict[str, str]) -> list[dict]:
    """Target glyph → các selector thử lần lượt trên máy (dump uiautomator2 làm hỏng glyph ngoài BMP).

    Tab đặt glyph ở content-desc của phần tử bấm được; nút ‹ header đặt glyph ở text của con.
    """
    if target.glyph is None:
        return []
    ch = glyphs[target.glyph]
    return [{"descriptionContains": ch}, {"textContains": ch}]


def device_selectors(target: Target, lex: Lexicon, glyphs: dict[str, str]) -> list[dict]:
    """Target → các selector hỏi thẳng trên máy (thử lần lượt), không cần dump.

    Rỗng khi target cần lọc theo cây UI (`after` = nằm dưới tiêu đề mục) → phải dùng locate() trên dump.
    """
    if target.after is not None:
        return []
    if target.glyph is not None:
        return target_selectors(target, glyphs)
    if target.desc is not None:
        v = _jre(target.desc)
        pat = {"exact": f"{v}", "prefix": f"{v}(, .*)?", "part": f"(.*, )?{v}(, .*)?", "contains": f".*{v}.*"}
        return [{"descriptionMatches": "(?s)" + pat[target.match]}]
    texts = lex.texts(target.key) if target.key is not None else {target.text} if target.text else set()
    if texts:
        return [{"textMatches": r"^\s*(" + "|".join(_jre(t) for t in sorted(texts)) + r")\s*$"}]
    raise ValueError("Target rỗng")


def spec_selector(spec: dict, lex: Lexicon) -> dict:
    """{"key": ...} / {"text": ...} (vd mốc cuộn) → selector trên máy."""
    return device_selectors(Target(key=spec.get("key"), text=spec.get("text")), lex, {})[0]


def locate(elements: list[Element], target: Target, glyphs: dict[str, str], lex: Lexicon) -> Element | None:
    """Phần tử bấm được ứng với target. None nếu không thấy, Ambiguous nếu nhiều hơn một."""
    if target.desc is not None:
        hits = [e for e in elements if _desc_match(e.desc, target.desc, target.match)]
    elif target.key is not None:
        want = lex.texts(target.key)
        hits = [e for e in elements if e.text.strip() in want]
    elif target.text is not None:
        hits = [e for e in elements if e.text.strip() == target.text]
    elif target.glyph is not None:
        ch = glyphs[target.glyph]
        hits = [e for e in elements if ch in e.text or ch in e.desc]
    else:
        raise ValueError("Target rỗng")
    if target.after is not None:
        floor = _below(elements, target.after, lex)
        hits = [e for e in hits if e.bounds[1] >= floor]

    found: dict[int, Element] = {}
    for e in hits:
        c = _clickable(elements, e)
        if c is not None:
            found[c.idx] = c
    if len(found) > 1:
        raise Ambiguous(f"{target} khớp {len(found)} phần tử: {[f.bounds for f in found.values()]}")
    return next(iter(found.values()), None)
