"""Server MCP (stdio) cho agent test Hunonic — Claude Code chạy theo .mcp.json, một tiến trình mỗi session.

Tool
  devices                                   thiết bị trong map + tool dùng được của từng cái
  <catalog>                                 mỗi hàm trong actions/catalog: tham số `device` + tham số của hàm
  screen · tap · back · scroll · open_app · goto     tự lái khi lạc / lỗi
  phone_time · wait                         đồng hồ điện thoại, chờ (tối đa WAIT_MAX s mỗi lần gọi)
  run_start · case_start · case_end · note · run_end ghi lượt chạy vào <session>/results/<HHMMSS>/ (web monitor đọc)

Mọi kết quả: {"status": "ok"|"failed", "result", "events", "route", "observations"}. Hunoscout vẫn tự gỡ trước
(nhận diện lại + lập lại đường, tối đa 3 lần) và ghi mọi lần lạc vào events. "failed" = Hunoscout không làm xong
(không phải kết luận app lỗi) → kèm context: màn nhận ra, điều cấm chạm, chữ/nút đang thấy (toạ độ), ảnh màn.
Agent tự quyết có phải lỗi không, tự lái bằng screen/tap/back/scroll/open_app/goto rồi gọi lại.
observations: HTTP (mitm flows.jsonl) + MQTT publish (topic, chiều) trong khoảng thời gian của lần gọi.

  ANDROID_SERIAL=2fc3878f .venv/bin/python -m module.mcp_server [--no-fresh]
Một điện thoại chỉ một bên điều khiển: không chạy cùng web điều khiển (module.web).
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import logging
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import anyio
import mcp_types as types
import yaml
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from .. import config
from .. import interact as adb
from ..actions.catalog import ACTIONS, BY_ID, _device, available, run
from ..actions.ui import node
from ..interact import u2 as U2
from ..parse_data import latest_response, parse_house
from ..scout import Scout
from ..ui_map.element import parse

log = logging.getLogger("mcp")
WAIT_MAX = 120
EVIDENCE = Path(os.environ.get("MITM_EVIDENCE", "~/Project/runtime_evidence/api_sniff")).expanduser()
TYPES = {"str": "string", "int": "integer", "bool": "boolean", "flag": "boolean"}
VERDICTS = ["PASS", "FAIL", "BLOCKED", "NEED-REVIEW"]


# ---- schema tool ----

def _schema(a: dict) -> dict:
    props = {"device": {"type": "string", "description": "tên thiết bị như trong app (lấy từ tool devices)"}}
    req = ["device"]
    for p in a["params"]:
        if p["type"] == "list":
            s = {"type": "array", "items": {"type": "string", **({"enum": list(p["choices"])} if p.get("choices") else {})}}
        elif p["type"] in ("choice", "tri"):
            s = {"type": "string", "enum": [c for c in p.get("choices", ["on", "off"]) if c]}
        else:
            s = {"type": TYPES[p["type"]]}
        s["description"] = p["label"] + (f" ({p['hint']})" if p.get("hint") else "")
        if "default" in p:
            s["default"] = p["default"]
        props[p["name"]] = s
        if p.get("required"):
            req.append(p["name"])
    return {"type": "object", "properties": props, "required": req, "additionalProperties": False}


def _retry(tool: str) -> str:
    if tool.endswith(("-get", "-list")) or tool in ("general-info", "history"):
        return "an toàn (chỉ đọc)"
    if tool.endswith("-set"):
        return "an toàn (đọc giá trị hiện tại trước khi đặt)"
    if tool.endswith("-add") or tool == "share":
        return "KHÔNG an toàn: có thể đã tạo — đọc danh sách trước rồi mới gọi lại"
    return "kiểm trước: đọc danh sách / trạng thái rồi mới gọi lại"


def _desc(a: dict) -> str:
    doc = (a["fn"].__doc__ or "").strip().split("\n\n")[0]
    return " ".join(x for x in (a["label"] + ".", "Thay đổi trạng thái thiết bị thật." if a.get("danger") else "",
                                doc, f"Gọi lại khi failed: {_retry(a['id'])}.") if x)


def _obj(props: dict, req: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": req or [], "additionalProperties": False}


S = {"type": "string"}
MANUAL = {
    "devices": ("Thiết bị trong map: tên (truyền nguyên văn vào `device`), id, loại, tool dùng được. Gọi trước.", _obj({})),
    "screen": ("Nhìn màn hiện tại: màn nhận ra trong map, điều cấm chạm, chữ/nút đang thấy kèm toạ độ, ảnh.", _obj({})),
    "tap": ("Tự lái: chạm theo chữ (text/desc) hoặc toạ độ x,y (pixel màn thật, lấy từ screen). hold=true = giữ "
            "~0.8 s (vào thiết bị từ ô thiết bị: ô thiết bị TAP = bật/tắt). Trả màn sau đó.",
            _obj({"text": S, "x": {"type": "integer"}, "y": {"type": "integer"}, "hold": {"type": "boolean"}})),
    "back": ("Tự lái: phím Back. Trả màn sau đó.", _obj({})),
    "scroll": ("Tự lái: cuộn, down = xem phần dưới. Trả màn sau đó.",
               _obj({"direction": {"type": "string", "enum": ["up", "down"]}}, ["direction"])),
    "open_app": ("Mở app Hunonic lên trước (app đóng / đang ở app khác). Trả màn sau đó.", _obj({})),
    "goto": ("Đi tới một màn trong map bằng navigator: id node hoặc đoạn chữ khớp duy nhất "
             "(vd 'history/' + tên thiết bị không đủ → dùng id đầy đủ trong lỗi / screen).", _obj({"node": S}, ["node"])),
    "phone_time": ("Giờ hiện tại trên điện thoại (YYYY-MM-DD HH:MM:SS) — tính giờ hẹn theo đồng hồ này.", _obj({})),
    "wait": (f"Chờ `seconds` giây (tối đa {WAIT_MAX}/lần — chờ lâu thì gọi lặp). Web hiện đang chờ gì. Trả giờ điện thoại.",
             _obj({"seconds": {"type": "integer"}, "reason": S}, ["seconds"])),
    "run_start": ("Bắt đầu lượt chạy: tạo <session_dir>/results/<HHMMSS>/ (đọc config.yaml của phiên). Gọi 1 lần đầu.",
                  _obj({"session_dir": S, "title": S}, ["session_dir"])),
    "case_start": ("Bắt đầu một testcase (web hiện đang chạy case này).", _obj({"id": S, "title": S}, ["id"])),
    "case_end": ("Kết luận testcase. checks: [{name, expected, actual, ok}]. verdict: " + " | ".join(VERDICTS),
                 _obj({"id": S, "verdict": {"type": "string", "enum": VERDICTS}, "summary": S,
                       "checks": {"type": "array", "items": {"type": "object"}}}, ["id", "verdict", "summary"])),
    "note": ("Ghi một dòng lên web (kế hoạch, suy luận, việc đang chờ).", _obj({"text": S}, ["text"])),
    "run_end": ("Kết thúc lượt chạy: ghi report.md (markdown) + tóm tắt.", _obj({"summary": S, "report_md": S}, ["summary"])),
}
TOOLS = [types.Tool(name=n, description=d, input_schema=s) for n, (d, s) in MANUAL.items()]
TOOLS += [types.Tool(name=a["id"], description=_desc(a), input_schema=_schema(a)) for a in ACTIONS]


# ---- quan sát: mitm jsonl đọc tiếp từ chỗ cũ ----

class Tail:
    def __init__(self, path: Path):
        self.path, self.pos, self.rows = path, 0, []

    def read(self) -> list[dict]:
        if not self.path.exists():
            return self.rows
        if self.path.stat().st_size < self.pos:          # file bị cắt / tạo lại
            self.pos, self.rows = 0, []
        with self.path.open("rb") as f:
            f.seek(self.pos)
            for line in f:
                if not line.endswith(b"\n"):
                    break
                self.pos += len(line)
                try:
                    self.rows.append(json.loads(line))
                except ValueError:
                    pass
        self.rows = self.rows[-3000:]
        return self.rows


def _topic(raw_b64: str) -> str | None:
    """Topic của gói MQTT PUBLISH đầu tiên trong frame (topic không mã hoá, payload AES)."""
    b = base64.b64decode(raw_b64)
    if not b or b[0] >> 4 != 3:
        return None
    i = 1
    while i < len(b) and b[i] & 0x80:
        i += 1
    i += 1
    n = int.from_bytes(b[i:i + 2], "big")
    return b[i + 2:i + 2 + n].decode(errors="replace")


def _ts(s: str) -> float:
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").timestamp()


class Observer:
    def __init__(self):
        self.http, self.ws = Tail(EVIDENCE / "flows.jsonl"), Tail(EVIDENCE / "socketio.jsonl")

    def window(self, t0: float, t1: float) -> dict:
        lo, hi = int(t0) - 1, t1 + 1
        http = [{"ts": r["ts"], "method": r["method"], "path": r["path"], "status": r["status"],
                 "req": json.dumps(r.get("req_body"), ensure_ascii=False)[:300] if r.get("req_body") else None}
                for r in self.http.read() if r.get("host", "").endswith("hunonicpro.com")
                and "/ws" != r.get("path") and lo <= _ts(r["ts"]) <= hi]
        mqtt = []
        for r in self.ws.read():
            if "mqtt" in r.get("url", "") and lo <= _ts(r["ts"]) <= hi and (tp := _topic(r.get("raw_b64", ""))):
                mqtt.append({"ts": r["ts"], "dir": "app→broker" if r["from_client"] else "broker→app", "topic": tp})
        return {"http": http, "mqtt": mqtt}


# ---- ghi lượt chạy (web monitor đọc) ----

def _write_json(p: Path, obj) -> None:
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(p)


class Run:
    def __init__(self, session_dir: Path, title: str | None):
        self.dir = session_dir / "results" / datetime.now().strftime("%H%M%S")
        (self.dir / "shots").mkdir(parents=True, exist_ok=True)
        (self.dir / "cases").mkdir(exist_ok=True)
        cfg = session_dir / "config.yaml"
        self.config = (yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}) if cfg.exists() else {}
        self.shots = 0
        self.status = {"run": self.dir.name, "session": str(session_dir), "title": title, "state": "running",
                       "started": _now(), "updated": _now(), "case": None, "cases": {}, "steps": 0, "last": None,
                       "waiting": None, "busy": None}
        (self.dir / "run.yaml").write_text(yaml.safe_dump(
            {"started": self.status["started"], "title": title, "session": str(session_dir), "config": self.config,
             "serial": adb.serial()}, allow_unicode=True, sort_keys=False), encoding="utf-8")
        self.save()

    def save(self) -> None:
        self.status["updated"] = _now()
        _write_json(self.dir / "status.json", self.status)

    def step(self, rec: dict) -> None:
        rec = {"ts": _now(), "case": (self.status["case"] or {}).get("id"), **rec}
        with (self.dir / "steps.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        self.status["steps"] += 1
        if rec.get("type") == "tool":
            self.status["last"] = {"tool": rec["tool"], "status": rec["status"], "ts": rec["ts"]}
        self.save()

    def shot(self, jpg: bytes) -> str:
        self.shots += 1
        name = f"shots/{self.shots:04d}.jpg"
        (self.dir / name).write_bytes(jpg)
        return name


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Events(logging.Handler):
    """Gom log của navigator / scout trong một lần gọi tool: 📍 bước đi + cảnh báo lạc."""
    def __init__(self):
        super().__init__(logging.INFO)
        self.buf: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.startswith("module") or record.name == "scout":
            self.buf.append(record)


# ---- app ----

class App:
    def __init__(self, fresh: bool):
        self.fresh, self.scout, self.run = fresh, None, None
        self.lock, self.obs, self.events = threading.Lock(), Observer(), Events()
        logging.getLogger().addHandler(self.events)

    def _scout(self) -> Scout:
        if self.scout is None:
            s = Scout()
            s.start(fresh=self.fresh)
            self.scout = s
        return self.scout

    def _forget(self) -> None:
        """Agent tự thao tác → không còn biết đường đã đi: nhận diện lại ở lần sau."""
        if self.scout:
            nav = self.scout.nav
            nav.cur, nav._els = None, None
            nav.stack.clear(), nav.came_from.clear(), nav.scroll.clear()

    def _screen(self) -> tuple[dict, bytes | None]:
        out: dict = {"app_foreground": adb.current_package() == config.APP_PACKAGE}
        jpg = None
        try:
            nav = self.scout.nav if self.scout else None
            if nav:
                cur = nav.where()
                out["screen"] = cur
                if cur:
                    out["danger"] = nav.g.nodes[cur].danger
                els = nav.elements()
            else:
                out["screen"] = None
                els = parse(adb.dump(), config.APP_PACKAGE)
            out["elements"] = [{"label": (e.text or e.desc).strip()[:80],
                                "xy": [(e.bounds[0] + e.bounds[2]) // 2, (e.bounds[1] + e.bounds[3]) // 2],
                                **({"click": True} if e.clickable else {})}
                               for e in els if (e.text or e.desc).strip()][:150]
            img = U2._dev().screenshot()
            img = img.convert("RGB").resize((540, int(img.height * 540 / img.width)))
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=70)
            jpg = buf.getvalue()
        except Exception as e:                       # thu thập context hỏng (mất adb…) → vẫn trả về, ghi rõ
            out["context_error"] = f"{type(e).__name__}: {e}"
        return out, jpg

    def _manual(self, name: str, a: dict):
        if name == "tap":
            if a.get("text"):
                b = (U2.locate({"text": a["text"]}) or U2.locate({"description": a["text"]})
                     or U2.locate({"textContains": a["text"]}))
                if b is None:
                    raise LookupError(f"không thấy chữ {a['text']!r} trên màn")
                x, y = (b[0] + b[2]) // 2, (b[1] + b[3]) // 2
            else:
                x, y = a["x"], a["y"]
            adb.hold(x, y, 800) if a.get("hold") else adb.tap(x, y)
        elif name == "back":
            adb.back()
        elif name == "scroll":
            w, h = adb.screen_size()
            y1, y2 = (int(h * 0.7), int(h * 0.35)) if a["direction"] == "down" else (int(h * 0.35), int(h * 0.7))
            adb.drag(w // 2, y1, y2)
        elif name == "open_app":
            adb.launch(config.APP_PACKAGE)
            time.sleep(1.5)
        self._forget()
        time.sleep(0.8)

    def _devices(self) -> list[dict]:
        s = self._scout()
        resp, observed = latest_response(config.EXPORTS)
        ids = {d.name.strip(): d.id for d in parse_house(resp, config.HOME_ID, observed.isoformat()).devices.values()}
        return [{"device": _device(nid).strip(), "id": ids.get(_device(nid).strip()), "type": Path(n.file).stem,
                 "tools": [a["id"] for a in available(s, nid)]}
                for nid, n in s.graph.nodes.items() if nid.startswith("infoDevice@") and _device(nid)]

    def _phone_time(self) -> str:
        return adb.adb._shell("date", "'+%Y-%m-%d %H:%M:%S'").strip()

    def _run_tool(self, name: str, a: dict):
        if name == "run_start":
            self.run = Run(Path(a["session_dir"]).expanduser(), a.get("title"))
            return {"run_dir": str(self.run.dir), "config": self.run.config}
        if name in ("case_start", "case_end", "note", "run_end") and self.run is None:
            raise RuntimeError("chưa gọi run_start")
        r = self.run
        if name == "case_start":
            r.status["case"] = {"id": a["id"], "title": a.get("title"), "started": _now()}
            r.step({"type": "case_start", "id": a["id"], "title": a.get("title")})
            return {"ok": True}
        if name == "case_end":
            rec = {"id": a["id"], "verdict": a["verdict"], "summary": a["summary"], "checks": a.get("checks", []),
                   "ended": _now(), "started": (r.status["case"] or {}).get("started")}
            _write_json(r.dir / "cases" / f"{a['id']}.json", rec)
            r.status["cases"][a["id"]] = a["verdict"]
            r.step({"type": "case_end", **rec})
            r.status["case"] = None
            r.save()
            return {"ok": True}
        if name == "note":
            r.step({"type": "note", "text": a["text"]})
            return {"ok": True}
        if name == "run_end":
            if a.get("report_md"):
                (r.dir / "report.md").write_text(a["report_md"], encoding="utf-8")
            r.status.update(state="done", summary=a["summary"])
            r.step({"type": "run_end", "summary": a["summary"]})
            return {"run_dir": str(r.dir)}
        raise KeyError(name)

    def call(self, name: str, a: dict) -> tuple[dict, bytes | None]:
        with self.lock:
            if name in ("run_start", "case_start", "case_end", "note", "run_end"):
                return {"status": "ok", "result": self._run_tool(name, a)}, None
            t0 = time.time()
            self.events.buf = []
            out: dict
            jpg = None
            if self.run:                         # web: tool đang chạy (step chỉ ghi khi xong)
                self.run.status["busy"] = {"tool": name, "args": a, "since": _now()}
                self.run.save()
            try:
                if name == "wait":
                    secs = max(0, min(int(a["seconds"]), WAIT_MAX))
                    if self.run:
                        self.run.status["waiting"] = {"until": datetime.fromtimestamp(t0 + secs).strftime("%H:%M:%S"),
                                                      "reason": a.get("reason")}
                        self.run.save()
                    time.sleep(secs)
                    out = {"status": "ok", "result": {"phone_time": self._phone_time()}}
                elif name == "phone_time":
                    out = {"status": "ok", "result": self._phone_time()}
                elif name == "devices":
                    out = {"status": "ok", "result": self._devices()}
                elif name == "screen":
                    ctx, jpg = self._screen()
                    out = {"status": "ok", "result": ctx}
                elif name in ("tap", "back", "scroll", "open_app"):
                    self._manual(name, a)
                    ctx, jpg = self._screen()
                    out = {"status": "ok", "result": ctx}
                elif name == "goto":
                    out = {"status": "ok", "result": self._scout().goto(a["node"])}
                else:
                    s = self._scout()
                    kw = dict(a)
                    device = kw.pop("device")
                    info = node(s, "infoDevice@", device)
                    if name not in [x["id"] for x in available(s, info)]:
                        raise ValueError(f"thiết bị {device!r} không có tool {name!r} (xem tool devices)")
                    out = {"status": "ok", "result": run(s, name, info, kw)}
            except Exception as e:
                log.exception("tool %s lỗi", name)
                ctx, jpg = self._screen()
                out = {"status": "failed", "error": type(e).__name__, "message": str(e), "tool": name, "args": a,
                       "retry": _retry(name), "context": ctx,
                       "hint": "Tự quyết có phải lỗi app không. Gỡ: screen/tap/back/scroll/open_app/goto rồi gọi lại."}
            finally:
                if self.run:
                    self.run.status["waiting"] = None
                    self.run.status["busy"] = None
            t1 = time.time()
            recs = self.events.buf
            out["events"] = [r.getMessage() for r in recs if r.levelno >= logging.WARNING]
            out["route"] = [r.getMessage().split("|")[0].replace("📍", "").strip() for r in recs
                            if r.getMessage().startswith("📍")]
            out["ms"] = int((t1 - t0) * 1000)
            out["observations"] = self.obs.window(t0, t1)
            if self.run:
                shot = self.run.shot(jpg) if jpg else None
                ctxd = out.get("context") if out["status"] == "failed" else (
                    out.get("result") if name in ("screen", "tap", "back", "scroll", "open_app") else None)
                res = json.dumps(out.get("result", out.get("message")), ensure_ascii=False, default=str)
                self.run.step({"type": "tool", "tool": name, "args": a, "status": out["status"], "ms": out["ms"],
                               "result": res[:4000], "error": out.get("error"), "events": out["events"],
                               "route": out["route"], "observations": out["observations"], "shot": shot,
                               "screen": ctxd.get("screen") if isinstance(ctxd, dict) else None})
            return out, jpg


def main(argv: list[str]) -> None:
    ap = argparse.ArgumentParser(prog="python -m module.mcp_server", description=__doc__.split("\n\n")[0])
    ap.add_argument("--no-fresh", action="store_true", help="dùng danh sách thiết bị export lần trước")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s.%(msecs)03d %(message)s", datefmt="%H:%M:%S",
                        stream=sys.stderr)
    for noisy in ("module.ui_map.pattern", "module.parse_data.rules"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    app = App(fresh=not args.no_fresh)

    async def list_tools(ctx, params) -> types.ListToolsResult:
        return types.ListToolsResult(tools=TOOLS)

    async def call_tool(ctx, params: types.CallToolRequestParams) -> types.CallToolResult:
        if params.name not in MANUAL and params.name not in BY_ID:
            return types.CallToolResult(content=[types.TextContent(type="text", text=f"không có tool {params.name!r}")],
                                        is_error=True)
        out, jpg = await anyio.to_thread.run_sync(app.call, params.name, params.arguments or {})
        content = [types.TextContent(type="text", text=json.dumps(out, ensure_ascii=False, default=str))]
        if jpg:
            content.append(types.ImageContent(type="image", data=base64.b64encode(jpg).decode(), mime_type="image/jpeg"))
        return types.CallToolResult(content=content, is_error=out["status"] == "failed")

    server = Server("hunoscout", instructions=__doc__.split("\n\n")[1], on_list_tools=list_tools, on_call_tool=call_tool)

    async def serve() -> None:
        async with stdio_server() as (r, w):
            await server.run(r, w, server.create_initialization_options())

    try:
        anyio.run(serve)
    finally:
        if app.scout:
            app.scout.stop("tắt mcp")


if __name__ == "__main__":
    main(sys.argv[1:])
