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
        alts = anchor if isinstance(anchor, list) else [anchor]
        if not any(_spec_hit(a if isinstance(a, dict) else {"key": a}, texts, lex) for a in alts):
            return False
    if node.check_text is None:
        return True
    want = node.check_text.strip()          # tên trong dữ liệu có thể thừa dấu cách (vd "Công tắc ")
    return any(e.text.strip() == want and _clickable(elements, e) is None for e in elements)


def _desc_match(desc: str, want: str, mode: str) -> bool:
    want = want.strip()
    if mode == "exact":
        return desc.strip() == want
    if mode == "prefix":                  # desc RN gộp nhãn con bằng ", "
        return desc.strip() == want or desc.strip().startswith(want + ", ")
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
    first = node.anchors[0] if node.anchors else None
    a = node.anchor or (first if isinstance(first, dict) else {"key": first} if first else None)
    return _spec_texts(a, lex) if a else set()


def _spec_texts(a: dict, lex: Lexicon) -> set[str]:
    """{"key": ..., "suffix": " {device.name}"} → chữ của key ở mọi ngôn ngữ + hậu tố (title ghép
    kiểu "Hẹn giờ Công tắc"); suffix đã được điền dữ liệu lúc bung pattern."""
    if "any" in a:
        return set().union(*(_spec_texts(s, lex) for s in a["any"]))
    if "key" in a:
        keys = a["key"] if isinstance(a["key"], list) else [a["key"]]
        return {(t + a.get("suffix", "")).strip() for k in keys for t in lex.texts(k)}
    if "text" in a:
        return {a["text"].strip()}
    raise ValueError(f"anchor không hỗ trợ: {a}")


def _spec_hit(a: dict, texts: set[str], lex: Lexicon) -> bool:
    """Màn có chữ khớp spec. "match": "prefix" → chữ trên màn chỉ cần bắt đầu bằng nó
    (vd "Danh sách người được chia sẻ (2)" ghép số)."""
    alts = _spec_texts(a, lex)
    if a.get("match") == "prefix":
        return any(t.startswith(x) for t in texts for x in alts)
    return bool(alts & texts)


def unique_selector(src: Node, dst: Node, lex: Lexicon) -> dict | None:
    """Selector chữ của một anchor CHỈ màn đích có (không nằm trong title/anchors màn nguồn).

    Dùng xác minh nhanh khi title hai màn trùng nhau (vd share list/add cùng "Chia sẻ thiết bị"): hỏi máy
    chữ riêng đó thay vì dump cả cây. Không có chữ riêng → None (rơi về dump).
    """
    spec = lambda a: a if isinstance(a, dict) else {"key": a}
    have = anchor_texts(src, lex) | ({src.check_text.strip()} if src.check_text else set())
    for anchor in src.anchors:
        for a in anchor if isinstance(anchor, list) else [anchor]:
            have |= _spec_texts(spec(a), lex)
    for anchor in dst.anchors:                   # nhóm [a, b, c] = chỉ cần một → gộp mọi chữ của nhóm vào 1 lần hỏi
        parts = sorted({_jre(t) + (".*" if spec(a).get("match") == "prefix" else r"\s*")
                        for a in (anchor if isinstance(anchor, list) else [anchor])
                        for t in _spec_texts(spec(a), lex) - have})
        if parts:
            return {"textMatches": r"(?s)^\s*(?:" + "|".join(parts) + ")$"}
    return None


def anchor_selectors(node: Node, lex: Lexicon) -> list[dict]:
    """Mỗi nhóm anchor của node → 1 selector (nhóm [a, b] = chỉ cần một); + tên riêng (check) nếu có.

    Đủ hết các selector trên màn = đang ở node — xác minh bằng vài lần hỏi máy, không dump cả màn.
    """
    spec = lambda a: a if isinstance(a, dict) else {"key": a}
    out = []
    for anchor in node.anchors:
        parts = sorted({_jre(t) + (".*" if spec(a).get("match") == "prefix" else r"\s*")
                        for a in (anchor if isinstance(anchor, list) else [anchor])
                        for t in _spec_texts(spec(a), lex)})
        if parts:
            out.append({"textMatches": r"(?s)^\s*(?:" + "|".join(parts) + ")$"})
    if node.check_text:
        out.append({"textMatches": r"^\s*" + _jre(node.check_text.strip()) + r"\s*$"})
    return out


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


def _header_row(elements: list[Element]) -> list[Element]:
    """Nút bấm được cùng hàng với nút cao nhất màn (lệch mép trên ≤ 20 px), trái → phải."""
    cl = [e for e in elements if e.clickable]
    if not cl:
        return []
    top = min(e.bounds[1] for e in cl)
    return sorted((e for e in cl if e.bounds[1] - top <= 20), key=lambda e: e.bounds[0])


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
    if target.after is not None or target.header is not None:
        return []
    if target.glyph is not None:
        return target_selectors(target, glyphs)
    if target.desc is not None:             # \s* hai đầu: tên thiết bị có thể thừa dấu cách ("AC, DC, Công tắc , Đang tắt")
        v = _jre(target.desc.strip())
        pat = {"exact": f"\\s*{v}\\s*", "prefix": f"\\s*{v}\\s*(, .*)?", "part": f"(.*, )?\\s*{v}\\s*(, .*)?", "contains": f".*{v}.*"}
        by_desc = {"descriptionMatches": "(?s)" + pat[target.match]}
        if target.match == "part":            # ô thiết bị: hỏi thẳng chữ tên (phần tử con trong ô) trước — nhanh hơn regex desc
            return [{"textMatches": rf"^\s*{v}\s*$"}, by_desc]
        return [by_desc]
    texts = lex.texts(target.key) if target.key is not None else {target.text.strip()} if target.text else set()
    if texts:
        return [{"textMatches": r"^\s*(" + "|".join(_jre(t) for t in sorted(texts)) + r")\s*$"}]
    raise ValueError("Target rỗng")


def spec_selector(spec: dict, lex: Lexicon) -> dict:
    """{"key": ...} / {"text": ...} (vd mốc cuộn) → selector trên máy."""
    return device_selectors(Target(key=spec.get("key"), text=spec.get("text")), lex, {})[0]


def locate(elements: list[Element], target: Target, glyphs: dict[str, str], lex: Lexicon) -> Element | None:
    """Phần tử bấm được ứng với target. None nếu không thấy, Ambiguous nếu nhiều hơn một."""
    if target.header is not None:
        row = _header_row(elements)
        return row[target.header] if -len(row) <= target.header < len(row) else None
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
