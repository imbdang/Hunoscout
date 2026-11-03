"""Trang web xem map dạng đồ thị; bấm vào node → route điện thoại tới màn đó, đo thời gian từng bước.

Chạy:  ANDROID_SERIAL=<serial> .venv/bin/python -m module.web [--no-fresh] [--port 8765]
Mở:    http://127.0.0.1:8765

Server giữ một Scout (đã qua IDLE/DISCOVERY → ACTIVE). Mỗi lần chỉ chạy một goto.
POST /api/goto trả NDJSON từng dòng: plan → step… (log khi lạc / đổi trạng thái) → done | error.
POST /api/discovery (NDJSON log… → done | error): mở lại app lấy danh sách thiết bị mới, dựng lại map, học core.
POST /api/refresh: dựng lại map từ pattern + danh sách đã lưu, không chạm điện thoại.
GET  /api/actions?node=…: hàm tương tác chạy được từ node (module/actions/catalog.py) — menu chuột phải.
POST /api/action {node, action, params} (NDJSON step… log… → done{result} | error): chạy hàm, tự route tới màn cần.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ..actions import catalog
from ..scout import Scout, State
from ..ui_map import Edge

PAGE = Path(__file__).with_name("index.html")
log = logging.getLogger("web")


def _edge(e: Edge, learned: bool) -> dict:
    return {"id": e.id, "src": e.src, "to": e.to, "gesture": e.action.gesture, "control": e.control,
            "cost_ms": e.cost_ms, "learned": learned, "back": e.back}


class _Forward(logging.Handler):
    """Chuyển log của scout (đổi trạng thái) và cảnh báo (lạc, lập lại đường) sang trình duyệt."""

    def __init__(self, cb, names: tuple[str, ...] = ("scout",)):
        super().__init__(logging.INFO)
        self.cb, self.names = cb, names

    def emit(self, rec: logging.LogRecord) -> None:
        if rec.name in self.names or rec.levelno >= logging.WARNING:
            self.cb({"type": "log", "level": rec.levelname, "msg": rec.getMessage()})


class App:
    def __init__(self, scout: Scout):
        self.s = scout
        self.lock = threading.Lock()

    def _ok(self, e: Edge) -> bool:
        return self.s.usable(e) and self.s.nav._back_ok(e)

    def graph(self) -> dict:
        s = self.s
        nodes = []
        for n in s.graph.nodes.values():
            anchor = s.res.get_anchor(n)
            nodes.append({
                "id": n.id, "route": n.route, "file": n.file, "explored": n.explored, "overlay": n.overlay,
                "title": anchor and {"text": anchor["text"], "band": anchor["band"]},
                "danger": n.danger,
                "controls": [{"key": k, "kind": c.get("kind"), "to": c.get("to"), "when": c.get("when"),
                              "danger": bool(c.get("danger")) or c.get("kind") == "danger",
                              "note": c.get("effect") or c.get("note")} for k, c in n.controls.items()],
            })
        edges = [_edge(e, s.res.get(e) is not None) for e in s.graph.edges()]
        return {"serial": s.serial, "state": s.state.name, "pointer": s.nav.pointer(), "busy": self.lock.locked(),
                "nodes": nodes, "edges": edges}

    def path(self, dst: str) -> tuple[dict, int]:
        cur = self.s.nav.cur
        if cur is None:
            return {"error": "chưa biết màn hiện tại — route lần đầu sẽ tự nhận diện"}, 200
        try:
            p = self.s.graph.path(cur, dst, ok=self._ok)
        except (LookupError, KeyError) as err:
            return {"error": str(err)}, 200
        return {"src": cur, "path": [_edge(e, self.s.res.get(e) is not None) for e in p],
                "est_ms": sum(e.cost_ms for e in p)}, 200

    def goto(self, dst: str, emit) -> None:
        s, t0 = self.s, time.monotonic()
        plan = self.path(dst)[0]
        emit({"type": "plan", "dst": dst, **plan})

        def moved(e: Edge, how: str, ms: int) -> None:
            emit({"type": "step", "edge": e.id, "src": e.src, "to": e.to, "control": e.control or e.action.gesture,
                  "ms": ms, "how": how, "t": int((time.monotonic() - t0) * 1000)})

        fwd = _Forward(emit)
        logging.getLogger().addHandler(fwd)
        s.nav.on_move = moved
        try:
            s.goto(dst)
            emit({"type": "done", "node": s.nav.cur, "total_ms": int((time.monotonic() - t0) * 1000)})
        except Exception as err:                 # Lost / không có đường / adb lỗi → báo lên trang, server vẫn chạy
            emit({"type": "error", "msg": f"{type(err).__name__}: {err}", "node": s.nav.cur,
                  "total_ms": int((time.monotonic() - t0) * 1000)})
        finally:
            s.nav.on_move = None
            logging.getLogger().removeHandler(fwd)


    def action(self, node_id: str, name: str, params: dict, emit) -> None:
        s, t0 = self.s, time.monotonic()
        emit({"type": "start", "node": node_id, "action": name, "params": params})

        def moved(e: Edge, how: str, ms: int) -> None:
            emit({"type": "step", "edge": e.id, "src": e.src, "to": e.to, "control": e.control or e.action.gesture,
                  "ms": ms, "how": how, "t": int((time.monotonic() - t0) * 1000)})

        fwd = _Forward(emit)
        logging.getLogger().addHandler(fwd)
        s.nav.on_move = moved
        try:
            out = catalog.run(s, name, node_id, params)
            emit({"type": "done", "result": out, "node": s.nav.cur, "total_ms": int((time.monotonic() - t0) * 1000)})
        except Exception as err:                 # ActionError / Lost / adb lỗi → báo lên trang, server vẫn chạy
            emit({"type": "error", "msg": f"{type(err).__name__}: {err}", "node": s.nav.cur,
                  "total_ms": int((time.monotonic() - t0) * 1000)})
        finally:
            s.nav.on_move = None
            logging.getLogger().removeHandler(fwd)

    def refresh(self) -> dict:
        s, old = self.s, self.s.nav
        before = set(s.graph.nodes) if s.graph else set()
        s.load(fresh=False)
        _keep_pointer(s, old)
        if s.state is not State.ACTIVE:          # vd discovery trước đó lỗi giữa chừng
            s._go(State.ACTIVE, "làm mới map từ web")
        after = set(s.graph.nodes)
        return {"added": sorted(after - before), "removed": sorted(before - after),
                "pruned": s.report.pruned, "warnings": s.report.warnings}

    def discovery(self, emit) -> None:
        s, t0 = self.s, time.monotonic()
        fwd = _Forward(emit, names=("scout", "module.ui_map.navigate"))
        logging.getLogger().addHandler(fwd)
        try:
            s.stop("discovery lại từ web")
            r = s.start(fresh=True)
            emit({"type": "done", "total_ms": int((time.monotonic() - t0) * 1000), "devices": r.devices,
                  "resolved": r.resolved, "anchors": sorted(r.anchors), "tiles": r.tiles, "failed": r.failed, "pruned": r.pruned,
                  "unexplored": len(r.unexplored), "warnings": r.warnings, "node": s.nav.cur})
        except Exception as err:                 # hook không ra danh sách / adb lỗi → báo lên trang
            emit({"type": "error", "msg": f"{type(err).__name__}: {err}",
                  "total_ms": int((time.monotonic() - t0) * 1000)})
        finally:
            logging.getLogger().removeHandler(fwd)

def _keep_pointer(s: Scout, old) -> None:
    """Map vừa dựng lại (Navigator mới): giữ vị trí 📍 cũ nếu node còn — không chạm màn hình."""
    if old is None or old.cur not in s.graph.nodes:
        return
    live = s.graph.nodes
    s.nav.cur = old.cur
    s.nav.stack = [x for x in old.stack if x in live]
    s.nav.scroll = {k: v for k, v in old.scroll.items() if k in live}
    s.nav.came_from = {k: v for k, v in old.came_from.items() if k in live and v in live}


class Handler(BaseHTTPRequestHandler):
    app: App
    def log_message(self, *args) -> None:
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj: dict, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def do_GET(self) -> None:
        u = urlparse(self.path)
        if u.path == "/":
            self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        elif u.path == "/api/graph":
            self._json(self.app.graph())
        elif u.path == "/api/path":
            self._json(*self.app.path(parse_qs(u.query).get("dst", [""])[0]))
        elif u.path == "/api/actions":
            self._json({"actions": catalog.available(self.app.s, parse_qs(u.query).get("node", [""])[0])})
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path not in ("/api/goto", "/api/where", "/api/refresh", "/api/discovery", "/api/action"):
            return self._send(404, b"not found", "text/plain")
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        dst = body.get("dst", "")
        if not self.app.lock.acquire(blocking=False):
            return self._json({"error": "đang chạy việc khác (route / discovery / hàm)"}, 409)
        try:
            if path == "/api/where":              # dump 1 lần, nhận diện màn hiện tại
                self.app.s.nav.where()
                return self._json(self.app.s.nav.pointer())
            if path == "/api/refresh":
                try:
                    return self._json(self.app.refresh())
                except Exception as err:          # pattern JSON sai / thiếu exports → báo lên trang
                    return self._json({"error": f"{type(err).__name__}: {err}"}, 500)
            if path == "/api/action":
                return self._stream(lambda emit: self.app.action(body.get("node", ""), body.get("action", ""),
                                                                 body.get("params") or {}, emit))
            self._stream(lambda emit: self.app.goto(dst, emit) if path == "/api/goto" else self.app.discovery(emit))
        finally:
            self.app.lock.release()

    def _stream(self, run) -> None:
        """NDJSON: mỗi sự kiện một dòng, gửi ngay khi có."""
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        alive = [True]

        def emit(ev: dict) -> None:
            if not alive[0]:
                return
            try:
                self.wfile.write((json.dumps(ev, ensure_ascii=False) + "\n").encode())
                self.wfile.flush()
            except OSError:                      # tab đóng giữa chừng: vẫn chạy hết, chỉ thôi gửi
                alive[0] = False

        run(emit)


def main(argv: list[str]) -> None:
    ap = argparse.ArgumentParser(prog="python -m module.web", description=__doc__.split("\n\n")[0])
    ap.add_argument("--no-fresh", action="store_true", help="dùng danh sách thiết bị export lần trước")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s.%(msecs)03d %(message)s", datefmt="%H:%M:%S",
                        stream=sys.stderr)
    for noisy in ("module.ui_map.pattern", "module.parse_data.rules"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    s = Scout()
    s.start(fresh=not args.no_fresh)
    Handler.app = App(s)
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    log.info("mở http://%s:%d  (Ctrl+C để dừng)", args.host, args.port)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        s.stop("tắt web")


if __name__ == "__main__":
    main(sys.argv[1:])
