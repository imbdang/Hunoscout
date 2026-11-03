"""Pattern + House → Map cụ thể của một nhà.

data/huno_pattern/
  core.json                         Home, quản lý phòng (placeholder phòng/thiết bị)
  root_type/<root_type>.json        màn của một loại thiết bị + nút dẫn sang feature
  feature/<feature>/<screen>.json   một màn của feature dùng chung (timer, general_info...)

Loại thiết bị chưa có root_type/<rt>.json → leaf sinh trong bộ nhớ (parse_data.leaf_doc).
Placeholder bung theo dữ liệu nhà: mỗi phòng / thiết bị / (feature × thiết bị) thành node riêng,
nên Dijkstra chạy thẳng trên graph đã bung.

Id node:  core "detailRoom[Nhà tắm]" · thiết bị "infoDevice@sswitch2v[Ổ cắm sk01]"
          · feature "general_info/infoDeviceCommonView[Ổ cắm sk01]"
Nút trong "controls" có "to" thì thành cạnh: "<screen>" (cùng file/feature), "feature:<tên>"
(màn entry của feature đó, cùng thiết bị), "@back" (về màn đã đi vào).
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path

from ..parse_data import House, leaf_doc
from .graph import Action, Edge, Map, Node, Target

log = logging.getLogger(__name__)

_FIELD = re.compile(r"\{(\w+)\.(\w+)\}")


def _read(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def _feature_refs(nodes: dict) -> set[str]:
    return {c["to"][8:] for pn in nodes.values() for c in pn.get("controls", {}).values()
            if str(c.get("to", "")).startswith("feature:")}


def load_docs(pattern_dir: Path, root_types: set[str]) -> dict:
    """→ {"core": doc, "devices": {rt: doc}, "features": {tên: {"entry": screen, "screens": {screen: doc}}}}"""
    devices = {}
    for rt in sorted(root_types):
        p = pattern_dir / "root_type" / f"{rt}.json"
        doc = _read(p) if p.exists() else leaf_doc(rt)
        if doc:
            devices[rt] = doc
    features: dict[str, dict] = {}
    todo = set().union(*(_feature_refs(d["nodes"]) for d in devices.values())) if devices else set()
    while todo:
        name = todo.pop()
        folder = pattern_dir / "feature" / name
        screens = {p.stem: _read(p) for p in sorted(folder.glob("*.json"))}
        if not screens:
            log.warning("feature %s: chưa có file trong %s", name, folder)
            continue
        entry = next((s for s, d in screens.items() if d.get("entry")), next(iter(screens)))
        features[name] = {"entry": entry, "screens": screens}
        todo |= _feature_refs(screens) - features.keys()
    return {"core": _read(pattern_dir / "core.json"), "devices": devices, "features": features}


def fill(template: str | None, ctx: dict) -> str | None:
    """"{room.name}" → "Nhà tắm" theo ctx = {"room": Room, "device": Device}."""
    if template is None:
        return None
    return _FIELD.sub(lambda m: str(getattr(ctx[m.group(1)], m.group(2))), template)


def _fill_deep(v, ctx):
    if isinstance(v, str):
        return fill(v, ctx)
    if isinstance(v, list):
        return [_fill_deep(x, ctx) for x in v]
    if isinstance(v, dict):
        return {k: _fill_deep(x, ctx) for k, x in v.items()}
    return v


def holds(expr: str, obj) -> bool:
    """Điều kiện đơn giản "a == 0 and b != x" trên field của obj. Không dùng eval."""
    for part in expr.split(" and "):
        name, op, raw = part.split(maxsplit=2)
        cur = getattr(obj, name)
        want = type(cur)(raw) if isinstance(cur, (int, float)) else raw
        if op == "==" and cur != want or op == "!=" and cur == want:
            return False
        if op not in ("==", "!="):
            raise ValueError(f"toán tử không hỗ trợ: {op!r} trong {expr!r}")
    return True


def _expand(spec: dict, ctx: dict, house: House) -> list[dict]:
    """Bung một placeholder thành danh sách ctx, mỗi phần tử gắn thêm 1 room / device."""
    items = list(house.rooms) if spec["from"] == "rooms" else list(house.devices.values())
    if "where" in spec:
        cond = fill(spec["where"], ctx)
        items = [x for x in items if holds(cond, x)]
    items.sort(key=lambda x: getattr(x, spec["order"]))
    return [ctx | {spec["bind"]: x} for x in items]


def _node(nid: str, pn: dict, ctx: dict, file: str) -> Node:
    return Node(id=nid, route=pn["route"], file=file, anchors=list(pn.get("anchors", [])),
                anchor=_fill_deep(pn.get("anchor"), ctx), check_text=fill(pn.get("check"), ctx),
                danger=list(pn.get("danger", [])), controls=_fill_deep(pn.get("controls", {}), ctx),
                scroll=_fill_deep(pn.get("scroll"), ctx), overlay=pn.get("overlay", False))


def _control_edge(key: str, c: dict) -> dict:
    """Nút trong "controls" → định nghĩa cạnh cùng dạng với "edges" của core.json."""
    return {"to": c["to"], "control": key, "when": c.get("when"), "cost": c.get("cost"),
            "action": {"gesture": c.get("gesture", "tap"), "target": c.get("target"), "ms": c.get("ms", 800)}}


def instantiate(docs: dict, house: House) -> tuple[Map, dict[str, str]]:
    """→ (Map, glyphs: tên icon → ký tự)."""
    core, devices, features = docs["core"], docs["devices"], docs["features"]
    places = core.get("placeholders", {})
    all_docs = [core, *devices.values(), *(s for f in features.values() for s in f["screens"].values())]
    glyphs = {name: chr(int(code, 16)) for d in all_docs for name, code in d.get("glyphs", {}).items()}
    base = {"home": house}                       # "{home.name}" dùng được ở mọi node

    for name, spec in places.items():
        req = spec.get("require")
        if req and not any(holds(req, x) for x in (house.rooms if spec["from"] == "rooms" else house.devices.values())):
            log.warning("placeholder %s: không có phần tử nào thoả %r", name, req)

    nodes: dict[str, Node] = {}
    todo: list[tuple[Node, dict, dict, callable]] = []   # (node, định nghĩa, ctx, hàm đổi "to" → id)

    # 1a. core: node có "param" thành một instance cho mỗi phòng
    for pid, pn in core["nodes"].items():
        param = pn.get("param")
        if param is None:
            insts = [(pid, base)]
        else:
            spec = places[param]
            insts = [(f"{pid}[{getattr(c[spec['bind']], spec['key'])}]", c) for c in _expand(spec, base, house)]
        for nid, ctx in insts:
            nodes[nid] = n = _node(nid, pn, ctx, "core")
            todo.append((n, pn, ctx, lambda to, c: fill(to, c)))

    # 1b. thiết bị: mỗi màn của root_type × mỗi thiết bị loại đó; kéo theo các feature nó dùng
    entries: dict[str, str] = {}                 # root_type → screen vào khi hold
    for rt, doc in devices.items():
        entries[rt] = doc["entry"]
        for dev in sorted((d for d in house.devices.values() if d.root_type == rt), key=lambda d: d.name):
            ctx = base | {"device": dev}
            sid = lambda s, rt=rt, dev=dev: f"{s}@{rt}[{dev.name}]"
            for screen, pn in doc["nodes"].items():
                nodes[sid(screen)] = n = _node(sid(screen), pn, ctx, f"root_type/{rt}")
                todo.append((n, pn, ctx, lambda to, c, sid=sid: sid(to)))
            seen, queue = set(), list(_feature_refs(doc["nodes"]))
            while queue:
                fname = queue.pop()
                if fname in seen or fname not in features:
                    continue
                seen.add(fname)
                fid = lambda s, f=fname, dev=dev: f"{f}/{s}[{dev.name}]"
                for screen, pn in features[fname]["screens"].items():
                    nodes[fid(screen)] = n = _node(fid(screen), pn, ctx, f"feature/{fname}")
                    todo.append((n, pn, ctx, lambda to, c, fid=fid: fid(to)))
                queue += list(_feature_refs(features[fname]["screens"]))

    def resolve_to(to: str, c: dict, local) -> str | None:
        dev = c.get("device")
        if to == "{device.entry}":
            if dev is None or dev.root_type not in entries:
                return None                      # loại thiết bị không có cạnh hold
            return f"{entries[dev.root_type]}@{dev.root_type}[{dev.name}]"
        if to.startswith("feature:"):
            f = to[8:]
            return f"{f}/{features[f]['entry']}[{dev.name}]" if f in features and dev else None
        return local(to, c)

    # 2. cạnh: "edges" (core) + "controls" có "to". "@back" để bước 3.
    back_from: list[tuple[Node, dict]] = []
    for node, pn, ctx, local in todo:
        eps = list(pn.get("edges", [])) + [_control_edge(k, c) for k, c in pn.get("controls", {}).items() if c.get("to")]
        for ep in eps:
            if ep["to"] == "@back":
                back_from.append((node, ep))
                continue
            for c in (_expand(places[ep["for_each"]], ctx, house) if ep.get("for_each") else [ctx]):
                to = resolve_to(ep["to"], c, local)
                dev = c.get("device")
                if to is None:
                    continue
                if ep.get("when") and dev is not None and not holds(ep["when"], dev):
                    log.info("bỏ cạnh %s → %s: không thoả %s", node.id, to, ep["when"])
                    continue
                if to not in nodes:
                    log.debug("bỏ cạnh %s → %s: chưa có node đích", node.id, to)
                    continue
                _add(node, to, ep, c, node.file)

    # 3. "@back" → một cạnh back về mỗi màn có cạnh đi vào node này
    for node, ep in back_from:
        for src in sorted({e.src for n in nodes.values() for e in n.edges if e.to == node.id}):
            _add(node, src, ep, base, node.file, back=True)

    return Map(list(nodes.values())), glyphs


def _add(node: Node, to: str, ep: dict, ctx: dict, file: str, back: bool = False) -> None:
    a = ep["action"]
    t = a.get("target")
    target = Target(**{k: (fill(v, ctx) if isinstance(v, str) else v) for k, v in t.items()}) if t else None
    eid = f"{node.id}>{to}"
    if any(e.id == eid for e in node.edges):
        eid = f"{eid}#{ep.get('control') or a['gesture']}"
    sig = hashlib.sha1(json.dumps([ep, to, target and target.desc], sort_keys=True, ensure_ascii=False)
                       .encode()).hexdigest()[:10]
    edge = Edge(id=eid, src=node.id, to=to, file=file, sig=sig, back=back, control=ep.get("control"),
                action=Action(a["gesture"], target, a.get("ms", 800)))
    if ep.get("cost"):
        edge.cost_ms = ep["cost"]
    node.edges.append(edge)
