"""Web theo dõi lượt test (chỉ đọc TestWorkspace, KHÔNG chạm điện thoại — chạy song song với agent được).

Cấu trúc đọc:  <root>/<suite>/sessions/<YYMMDD>/<thiết bị>/{config.yaml, results/<HHMMSS>/}
               <root>/<suite>/testcases/<thiết bị>/**/*.yaml
Lượt chạy (server MCP ghi): status.json · run.yaml · steps.jsonl · cases/<id>.json · shots/*.jpg · report.md

  .venv/bin/python -m module.monitor --root ~/TestWorkspace/test [--port 8766]
"""
from __future__ import annotations

import argparse
import json
import logging
import mimetypes
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import yaml

log = logging.getLogger("monitor")
HTML = Path(__file__).with_name("index.html")
CLAWD = Path(__file__).with_name("clawd")      # ảnh agent theo tâm trạng (xem clawd/SOURCE.txt)


def _json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _yaml(p: Path):
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as e:
        return {"_error": str(e)}


class Workspace:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def inside(self, p: str) -> Path:
        path = Path(p).resolve()
        if path != self.root and self.root not in path.parents:
            raise PermissionError(p)
        return path

    def tree(self) -> list[dict]:
        out = []
        for suite in sorted(p for p in self.root.iterdir() if (p / "sessions").is_dir()):
            dates = []
            for day in sorted((suite / "sessions").iterdir(), reverse=True):
                if not day.is_dir():
                    continue
                devs = []
                for dev in sorted(p for p in day.iterdir() if p.is_dir()):
                    res = dev / "results"
                    runs = [dict(_json(r / "status.json") or {}, dir=str(r))
                            for r in sorted((p for p in res.iterdir() if p.is_dir()), reverse=True)
                            if (r / "status.json").exists()] if res.is_dir() else []
                    devs.append({"name": dev.name, "dir": str(dev), "config": _yaml(dev / "config.yaml") or {},
                                 "testcases": str(suite / "testcases" / dev.name), "runs": runs})
                dates.append({"date": day.name, "devices": devs})
            out.append({"suite": suite.name, "dir": str(suite), "sessions": dates})
        return out

    def run(self, d: Path) -> dict:
        cases = {p.stem: _json(p) for p in sorted((d / "cases").glob("*.json"))}
        report = d / "report.md"
        return {"status": _json(d / "status.json"), "meta": _yaml(d / "run.yaml"), "cases": cases,
                "report": report.read_text(encoding="utf-8") if report.exists() else None}

    def steps(self, d: Path, start: int) -> dict:
        p = d / "steps.jsonl"
        if not p.exists():
            return {"steps": [], "next": 0}
        lines = p.read_text(encoding="utf-8").splitlines()
        out = []
        for line in lines[start:]:
            try:
                out.append(json.loads(line))
            except ValueError:
                out.append({"type": "broken", "raw": line[:300]})
        return {"steps": out, "next": len(lines)}

    def testcases(self, d: Path) -> list[dict]:
        out = []
        for p in sorted(d.rglob("*.yaml")):
            tc = _yaml(p) or {}
            tc["_file"] = str(p.relative_to(d))
            out.append(tc)
        return out


class Handler(BaseHTTPRequestHandler):
    ws: Workspace

    def log_message(self, fmt, *args):
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _ok(self, obj) -> None:
        self._send(200, json.dumps(obj, ensure_ascii=False, default=str).encode(), "application/json; charset=utf-8")

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path == "/":
                self._send(200, HTML.read_bytes(), "text/html; charset=utf-8")
            elif u.path.startswith("/clawd/") and u.path.endswith(".svg"):
                self._send(200, (CLAWD / Path(u.path).name).read_bytes(), "image/svg+xml")
            elif u.path == "/api/tree":
                self._ok({"root": str(self.ws.root), "suites": self.ws.tree()})
            elif u.path == "/api/run":
                self._ok(self.ws.run(self.ws.inside(q["dir"])))
            elif u.path == "/api/steps":
                self._ok(self.ws.steps(self.ws.inside(q["dir"]), int(q.get("from", 0))))
            elif u.path == "/api/testcases":
                self._ok(self.ws.testcases(self.ws.inside(q["dir"])))
            elif u.path == "/file":
                p = self.ws.inside(q["path"])
                self._send(200, p.read_bytes(), mimetypes.guess_type(p.name)[0] or "application/octet-stream")
            else:
                self._send(404, b"not found", "text/plain")
        except PermissionError:
            self._send(403, b"ngoai workspace", "text/plain")
        except (KeyError, FileNotFoundError) as e:
            self._send(404, str(e).encode(), "text/plain")


def main(argv: list[str]) -> None:
    ap = argparse.ArgumentParser(prog="python -m module.monitor", description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", default="~/TestWorkspace/test", help="thư mục chứa các suite (<suite>/sessions, testcases)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8766)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S", stream=sys.stderr)
    Handler.ws = Workspace(Path(args.root).expanduser())
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    log.info("theo dõi %s → http://%s:%d", Handler.ws.root, args.host, args.port)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main(sys.argv[1:])
