"""Server MCP (stdio) cho agent test Hunonic — Claude Code chạy theo .mcp.json, một tiến trình mỗi session.

Tool
  devices                                   thiết bị trong map + tool dùng được của từng cái
  houses · house_switch                     nhà của tài khoản, đổi nhà đang chọn trên app (map dựng lại theo nhà)
  config_nearby · config_ble                thiết bị BLE xung quanh (Thử lại khi sót), cấu hình thiết bị mới qua BLE
  <catalog>                                 mỗi hàm trong actions/catalog: tham số `device` + tham số của hàm
  screen · tap · back · scroll · open_app · goto     tự lái khi lạc / lỗi
  phone_time · wait                         đồng hồ điện thoại, chờ (tối đa WAIT_MAX s mỗi lần gọi)
  evidence                                  HTTP + MQTT (đã giải mã) theo khoảng giờ — đối chiếu case chạy song song
  run_start · case_start · case_end · note · run_end ghi lượt chạy vào <session>/results/<HHMMSS>/ (web monitor đọc)

Mọi kết quả: {"status": "ok"|"failed", "result", "events", "route", "observations"}. Hunoscout vẫn tự gỡ trước
(nhận diện lại + lập lại đường, tối đa 3 lần) và ghi mọi lần lạc vào events. "failed" = Hunoscout không làm xong
(không phải kết luận app lỗi) → kèm context: màn nhận ra, điều cấm chạm, chữ/nút đang thấy (toạ độ), ảnh màn.
Agent tự quyết có phải lỗi không, tự lái bằng screen/tap/back/scroll/open_app/goto rồi gọi lại.
observations: HTTP (mitm flows.jsonl: trường request đã che token + response) + MQTT (đã giải mã) trong khoảng
thời gian của lần gọi. Nhiều case mở cùng lúc: case_start khai `claims` (tài nguyên + khoảng giờ) — trùng thì bị từ
chối; mọi tool nhận `case` để ghi bước vào đúng case. config.yaml `houses_allowed`: chỉ được dùng các nhà đó.

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
import re
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import anyio
import mcp_types as types
import yaml
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from .. import config
from .. import interact as adb
from ..actions.catalog import ACTIONS, BY_ID, _device, available, run
from ..actions.config import config_ble, nearby
from ..actions.house import houses, switch_house
from ..actions.ui import node
from ..interact import u2 as U2
from ..parse_data import latest_response, parse_house
from ..scout import Scout
from ..ui_map.element import parse

log = logging.getLogger("mcp")
WAIT_MAX = 120
EVIDENCE_MAX = 200      # dòng mỗi loại (HTTP / MQTT) một lần gọi evidence
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
    "houses": ("Nhà của tài khoản: id, tên, vai trò (1 chủ / 2 được chia sẻ), số phòng / thiết bị; current = nhà map "
               "đang dùng (phải trùng nhà đang mở trên app).", _obj({})),
    "house_switch": ("Đổi nhà đang chọn trên app (Home → bấm tên nhà → chọn trong 'Quản lý nhà') rồi dựng map của "
                     "nhà đó. Sau đó gọi devices để xem thiết bị của nhà mới.", _obj({"house": S}, ["house"])),
    "config_nearby": ("Thêm thiết bị (Home → +): tên thiết bị ở 'Thiết bị có sẵn xung quanh' (quét BLE ~10 s/lượt). "
                      "want chưa thấy → bấm Thử lại, tối đa rounds lượt (mặc định 3). Tên = tên mặc định của loại.",
                      _obj({"want": S, "rounds": {"type": "integer"}})),
    "config_ble": ("Cấu hình thiết bị mới qua BLE: chọn ô `device` ở 'Thiết bị có sẵn xung quanh' (Thử lại khi sót) → "
                   "thiết bị Wi-Fi: `wifi` + `password`; thiết bị chọn loại cấu hình (NeoR6, cảm biến khói): `mode` "
                   "hub (mesh qua bộ trung tâm) | direct (BLE) → (từng có cấu hình: restore=false như mới / true khôi "
                   "phục) → `name` / `room` ở màn cuối → Hoàn thành → dựng lại map. Trả tên thiết bị mới. Ô trùng tên → "
                   "lỗi. Thiết bị tự tắt chế độ cấu hình sau một lúc → gọi ngay sau khi thiết bị vào cấu hình.",
                   _obj({"device": S, "wifi": S, "password": S, "restore": {"type": "boolean"},
                         "mode": {"type": "string", "enum": ["hub", "direct"]}, "name": S, "room": S}, ["device"])),
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
    "evidence": ("Bằng chứng theo GIỜ (đồng hồ máy tính ≈ điện thoại, lệch ~1 s): HTTP (trường request đã che token, "
                 "response status/message/data) + MQTT đã giải mã (vd Module Input bật/tắt: {\"swinputv2\": 0, "
                 "\"action\": 1|2} — 1 bật, 2 tắt; app→broker = lệnh app gửi, broker→app = thiết bị trả) trong "
                 "[since, until]. `device` lọc theo thiết bị, `path` lọc đoạn path HTTP. Tối đa "
                 f"{EVIDENCE_MAX} dòng mỗi loại (mới nhất). Không chạm điện thoại.",
                 _obj({"since": {**S, "description": "HH:MM[:SS] hôm nay | YYYY-MM-DD HH:MM:SS"},
                       "until": {**S, "description": "trống = bây giờ"}, "device": S,
                       "kind": {"type": "string", "enum": ["all", "http", "mqtt"]}, "path": S}, ["since"])),
    "run_start": ("Bắt đầu lượt chạy: tạo <session_dir>/results/<HHMMSS>/ (đọc config.yaml của phiên). Gọi 1 lần đầu.",
                  _obj({"session_dir": S, "title": S}, ["session_dir"])),
    "case_start": ("Mở một testcase (web hiện các case đang mở). Nhiều case mở cùng lúc được (chạy song song): "
                   "`claims` = tài nguyên case giữ [{res, from?, to?}] (giờ HH:MM[:SS] điện thoại; thiếu from = bây "
                   "giờ, thiếu to = tới case_end). Trùng res + chồng giờ với case đang mở → failed kèm case xung đột.",
                   _obj({"id": S, "title": S, "claims": {"type": "array", "items": {
                       "type": "object", "properties": {"res": S, "from": S, "to": S}, "required": ["res"]}}}, ["id"])),
    "case_end": ("Kết luận testcase. checks: [{name, expected, actual, ok}]. verdict: " + " | ".join(VERDICTS),
                 _obj({"id": S, "verdict": {"type": "string", "enum": VERDICTS}, "summary": S,
                       "checks": {"type": "array", "items": {"type": "object"}}}, ["id", "verdict", "summary"])),
    "note": ("Ghi một dòng lên web (kế hoạch, suy luận, việc đang chờ). `case` = case của dòng này.",
             _obj({"text": S}, ["text"])),
    "run_end": ("Kết thúc lượt chạy: ghi report.md (markdown) + tóm tắt.", _obj({"summary": S, "report_md": S}, ["summary"])),
}
TOOLS = [types.Tool(name=n, description=d, input_schema=s) for n, (d, s) in MANUAL.items()]
TOOLS += [types.Tool(name=a["id"], description=_desc(a), input_schema=_schema(a)) for a in ACTIONS]
for _t in TOOLS:                         # ghi bước vào đúng case khi nhiều case đang mở
    if _t.name not in ("run_start", "case_start", "case_end", "run_end"):
        _t.input_schema["properties"]["case"] = {"type": "string", "description": "id case mà lần gọi này phục vụ"}


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
        self.rows = self.rows[-30000:]
        return self.rows


def _publishes(raw: bytes) -> list[tuple[str, bytes]]:
    """(topic, payload) của mọi gói MQTT PUBLISH trong frame (topic không mã hoá, payload AES)."""
    out, i = [], 0
    while i + 1 < len(raw):
        b0, n, mult, j = raw[i], 0, 1, i + 1
        while j < len(raw):
            n += (raw[j] & 0x7F) * mult
            j += 1
            if not raw[j - 1] & 0x80:
                break
            mult *= 128
        if j + n > len(raw):
            break
        if b0 >> 4 == 3:
            p = raw[j:j + n]
            k = 2 + int.from_bytes(p[:2], "big")
            out.append((p[2:k].decode(errors="replace"), p[k + (2 if (b0 >> 1) & 3 else 0):]))
        i = j + n
    return out


_ZERO = b"0" * 16


def _decrypt(root_id: str, data: bytes) -> dict | None:
    """Payload AES-CBC: key/iv lấy từ root_id (đoạn thứ 3 của topic u/<user>/<root_id>/<num>) — như
    HunonicMitm/decrypt_sdoor.py. Không trả / ghi key."""
    if not data or len(data) % 16:
        return None
    try:
        pad = padding.PKCS7(128).padder()
        enc = Cipher(algorithms.AES(_ZERO), modes.CBC(_ZERO)).encryptor()
        tmp = enc.update(pad.update(root_id.encode()) + pad.finalize()) + enc.finalize()
        dec = Cipher(algorithms.AES(tmp[4:20]), modes.CBC(tmp[12:28])).decryptor()
        unpad = padding.PKCS7(128).unpadder()
        return json.loads(unpad.update(dec.update(data) + dec.finalize()) + unpad.finalize())
    except Exception:
        return None


SECRET = re.compile(r"token|pass|sign|secret|^key$|^iv$|ssid", re.I)


def _mask(o):
    if isinstance(o, dict):
        return {k: "***" if SECRET.search(str(k)) else _mask(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_mask(v) for v in o]
    return o


def _fields(body):
    """Request body → dict trường (multipart / JSON), token / chữ ký thay bằng ***."""
    if isinstance(body, str):
        if body.startswith("--"):
            sep, out = body.split("\r\n", 1)[0], {}
            for part in body.split(sep)[1:]:
                head, _, val = part.partition("\r\n\r\n")
                if m := re.search(r'name="([^"]+)"', head):
                    out[m.group(1)] = val.rstrip("\r\n")
            body = out
        else:
            try:
                body = json.loads(body)
            except ValueError:
                return "***" if SECRET.search(body) else body[:200]
    return _mask(body)


def _clip(o, n: int):
    s = json.dumps(o, ensure_ascii=False, default=str)
    return o if len(s) <= n else s[:n] + "…"


def _ts(s: str) -> float:
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").timestamp()


class Observer:
    """HTTP (mitm flows.jsonl) + MQTT đã giải mã (socketio.jsonl) theo khoảng giờ. root: root_id → tên thiết bị."""

    def __init__(self):
        self.http, self.ws = Tail(EVIDENCE / "flows.jsonl"), Tail(EVIDENCE / "socketio.jsonl")
        self.root: dict[str, str] = {}

    def _http(self, lo: float, hi: float, n: int) -> list[dict]:
        out = []
        for r in self.http.read():
            if not r.get("host", "").endswith("hunonicpro.com") or r.get("path") == "/ws" or not lo <= _ts(r["ts"]) <= hi:
                continue
            resp = r.get("resp_body")
            if isinstance(resp, str):
                try:
                    resp = json.loads(resp)
                except ValueError:
                    pass
            if isinstance(resp, dict):
                resp = {k: resp[k] for k in ("status", "message", "data") if k in resp}
            out.append({"ts": r["ts"], "method": r["method"], "path": r["path"], "status": r["status"],
                        "req": _clip(_fields(r.get("req_body")), n) if r.get("req_body") else None,
                        "resp": _clip(_mask(resp), n) if resp else None})
        return out

    def _mqtt(self, lo: float, hi: float, n: int) -> list[dict]:
        out = []
        for r in self.ws.read():
            if "mqtt" not in r.get("url", "") or not lo <= _ts(r["ts"]) <= hi:
                continue
            for topic, payload in _publishes(base64.b64decode(r.get("raw_b64", ""))):
                parts = topic.split("/")
                root = parts[2] if len(parts) > 2 and parts[0] == "u" else ""
                msg = _decrypt(root, payload) if root else None
                out.append({"ts": r["ts"], "dir": "app→broker" if r["from_client"] else "broker→app",
                            "device": self.root.get(root, root or topic),
                            "msg": _clip(_mask(msg), n) if msg is not None else None})
        return out

    def window(self, t0: float, t1: float) -> dict:
        lo, hi = int(t0) - 1, t1 + 1
        return {"http": self._http(lo, hi, 300), "mqtt": self._mqtt(lo, hi, 200)}

    def query(self, lo: float, hi: float, kind: str, device: dict | None, path: str | None) -> dict:
        """Tool evidence: lọc theo thiết bị (id / root_id trong request, MQTT của root) + đoạn path."""
        out = {}
        if kind in ("all", "http"):
            rows = self._http(lo, hi, 800)
            if device:
                rows = [x for x in rows if device["id"] in json.dumps(x["req"], ensure_ascii=False)
                        or device["root_id"] in json.dumps(x["req"], ensure_ascii=False) or device["id"] in x["path"]]
            if path:
                rows = [x for x in rows if path in x["path"]]
            out["http"] = rows[-EVIDENCE_MAX:]
        if kind in ("all", "mqtt"):
            rows = self._mqtt(lo, hi, 400)
            if device:
                rows = [x for x in rows if x["device"] == device["name"]]
            out["mqtt"] = rows[-EVIDENCE_MAX:]
        return out


# ---- ghi lượt chạy (web monitor đọc) ----

def _write_json(p: Path, obj) -> None:
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(p)


class Run:
    def __init__(self, session_dir: Path, title: str | None):
        cfg = session_dir / "config.yaml"           # đọc trước: config hỏng thì không để lại thư mục lượt rỗng
        self.config = (yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}) if cfg.exists() else {}
        self.dir = session_dir / "results" / datetime.now().strftime("%H%M%S")
        (self.dir / "shots").mkdir(parents=True, exist_ok=True)
        (self.dir / "cases").mkdir(exist_ok=True)
        self.shots = 0
        self.status = {"run": self.dir.name, "session": str(session_dir), "title": title, "state": "running",
                       "started": _now(), "updated": _now(), "case": None, "active": {}, "cases": {}, "steps": 0,
                       "last": None, "waiting": None, "busy": None}
        (self.dir / "run.yaml").write_text(yaml.safe_dump(
            {"started": self.status["started"], "title": title, "session": str(session_dir), "config": self.config,
             "serial": adb.serial()}, allow_unicode=True, sort_keys=False), encoding="utf-8")
        self.save()

    def save(self) -> None:
        self.status["updated"] = _now()
        _write_json(self.dir / "status.json", self.status)

    def step(self, rec: dict) -> None:
        act = self.status["active"]
        rec = {"ts": _now(), **rec}
        if not rec.get("case"):              # không nói case nào: chỉ một case đang mở thì là case đó
            rec["case"] = next(iter(act)) if len(act) == 1 else None
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


def _when(v: str | None) -> str | None:
    """'HH:MM[:SS]' (hôm nay) | 'YYYY-MM-DD HH:MM[:SS]' → 'YYYY-MM-DD HH:MM:SS'."""
    if not v or not str(v).strip():
        return None
    v = str(v).strip()
    if len(v) <= 8:
        v = datetime.now().strftime("%Y-%m-%d ") + v
    return datetime.fromisoformat(v).strftime("%Y-%m-%d %H:%M:%S")


def _claims(raw: list[dict] | None) -> list[dict]:
    out = []
    for c in raw or []:
        f, t = _when(c.get("from")) or _now(), _when(c.get("to"))
        if t and t <= f:
            raise ValueError(f"claim {c}: to phải sau from")
        out.append({"res": str(c["res"]).strip(), "from": f, "to": t})
    return out


def _conflicts(new: list[dict], active: dict) -> list[str]:
    """Cùng res + khoảng giờ chồng nhau (to None = tới case_end). Chạm mép (to == from) không tính."""
    out = []
    for cid, c in active.items():
        for a in c["claims"]:
            for b in new:
                if a["res"] == b["res"] and (b["to"] is None or a["from"] < b["to"]) and (a["to"] is None or b["from"] < a["to"]):
                    out.append(f"{b['res']} {b['from'][11:]}–{b['to'][11:] if b['to'] else 'hết case'} "
                               f"trùng case {cid} ({a['from'][11:]}–{a['to'][11:] if a['to'] else 'hết case'})")
    return out


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
            self._house_devices()
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
        ids = {d.name.strip(): d.id for d in parse_house(resp, s.home_id, observed.isoformat()).devices.values()}
        return [{"device": _device(nid).strip(), "id": ids.get(_device(nid).strip()), "type": Path(n.file).stem,
                 "tools": [a["id"] for a in available(s, nid)]}
                for nid, n in s.graph.nodes.items() if nid.startswith("infoDevice@") and _device(nid)]

    def _phone_time(self) -> str:
        return adb.adb._shell("date", "'+%Y-%m-%d %H:%M:%S'").strip()

    def _house_devices(self) -> list[dict]:
        """Thiết bị nhà đang dùng (response đã lưu) + cập nhật bảng root_id → tên cho MQTT."""
        resp, _ = latest_response(config.EXPORTS)
        home = next((h for h in resp["data"] if str(h["id"]) == self._scout().home_id), {})
        devs = [d for r in home.get("rooms") or [] for d in r.get("devices") or []]
        self.obs.root = {d["root_id"]: (d.get("name") or "").strip() for d in devs if d.get("root_id")}
        return devs

    def _device_ids(self, name: str) -> dict:
        d = next((d for d in self._house_devices() if (d.get("name") or "").strip() == name.strip()), None)
        if d is None:
            raise ValueError(f"không có thiết bị {name!r} trong nhà đang dùng")
        return {"id": str(d["id"]), "root_id": d["root_id"], "name": name.strip()}

    def _allowed(self) -> set[str] | None:
        hs = self.run.config.get("houses_allowed") if self.run else None
        return {str(h).strip() for h in hs} if hs else None

    def _house_check(self, target: str | None = None) -> None:
        """config.yaml houses_allowed (id hoặc tên): chỉ được đổi sang / thao tác thiết bị trong các nhà đó."""
        ok = self._allowed()
        if ok is None:
            return
        s = self._scout()
        hs = houses(s)
        want = target if target is not None else s.home_id
        h = next((h for h in hs if want.strip() in (h["id"], h["name"])), None)
        if h is None or not ({h["id"], h["name"]} & ok):
            raise PermissionError(f"nhà {want!r} không có trong houses_allowed {sorted(ok)} của phiên"
                                  + ("" if target else " — house_switch sang nhà được phép trước"))

    def _run_tool(self, name: str, a: dict):
        if name == "run_start":
            self.run = Run(Path(a["session_dir"]).expanduser(), a.get("title"))
            return {"run_dir": str(self.run.dir), "config": self.run.config}
        if name in ("case_start", "case_end", "note", "run_end") and self.run is None:
            raise RuntimeError("chưa gọi run_start")
        r = self.run
        act = r.status["active"]
        if name == "case_start":
            if a["id"] in act:
                raise ValueError(f"case {a['id']} đang mở")
            claims = _claims(a.get("claims"))
            if bad := _conflicts(claims, act):
                raise ValueError("xung đột tài nguyên: " + "; ".join(bad))
            act[a["id"]] = {"title": a.get("title"), "started": _now(), "claims": claims}
            r.status["case"] = {"id": a["id"], "title": a.get("title"), "started": act[a["id"]]["started"]}
            r.step({"type": "case_start", "case": a["id"], "id": a["id"], "title": a.get("title"), "claims": claims})
            return {"ok": True, "active": {k: v["claims"] for k, v in act.items()}}
        if name == "case_end":
            cur = act.pop(a["id"], None) or {}
            rec = {"id": a["id"], "verdict": a["verdict"], "summary": a["summary"], "checks": a.get("checks", []),
                   "ended": _now(), "started": cur.get("started"), "claims": cur.get("claims", [])}
            _write_json(r.dir / "cases" / f"{a['id']}.json", rec)
            r.status["cases"][a["id"]] = a["verdict"]
            r.step({"type": "case_end", "case": a["id"], **rec})
            last = next(reversed(act), None)
            r.status["case"] = {"id": last, "title": act[last]["title"], "started": act[last]["started"]} if last else None
            r.save()
            return {"ok": True, "active": list(act)}
        if name == "note":
            r.step({"type": "note", "text": a["text"], "case": a.get("case")})
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
                try:
                    return {"status": "ok", "result": self._run_tool(name, a)}, None
                except Exception as e:
                    return {"status": "failed", "error": type(e).__name__, "message": str(e), "tool": name}, None
            a = dict(a)
            case = a.pop("case", None)
            t0 = time.time()
            self.events.buf = []
            out: dict
            jpg = None
            shown = {**a, "password": "***"} if "password" in a else a   # mật khẩu wifi không vào log / web
            if self.run:                         # web: tool đang chạy (step chỉ ghi khi xong)
                self.run.status["busy"] = {"tool": name, "args": shown, "since": _now(), "case": case}
                self.run.save()
            try:
                if name in ("config_nearby", "config_ble", "goto") or name in BY_ID:
                    self._house_check()
                if name == "wait":
                    secs = max(0, min(int(a["seconds"]), WAIT_MAX))
                    if self.run:
                        self.run.status["waiting"] = {"until": datetime.fromtimestamp(t0 + secs).strftime("%H:%M:%S"),
                                                      "reason": a.get("reason"), "case": case}
                        self.run.save()
                    time.sleep(secs)
                    out = {"status": "ok", "result": {"phone_time": self._phone_time()}}
                elif name == "phone_time":
                    out = {"status": "ok", "result": self._phone_time()}
                elif name == "devices":
                    out = {"status": "ok", "result": self._devices()}
                elif name == "houses":
                    out = {"status": "ok", "result": houses(self._scout())}
                elif name == "house_switch":
                    self._house_check(a["house"])
                    out = {"status": "ok", "result": switch_house(self._scout(), a["house"])}
                    self._house_devices()
                elif name == "evidence":
                    lo, hi = _ts(_when(a["since"])), _ts(_when(a.get("until")) or _now())
                    dev = self._device_ids(a["device"]) if a.get("device") else None
                    out = {"status": "ok", "result": self.obs.query(lo, hi + 1, a.get("kind") or "all", dev, a.get("path"))}
                elif name == "config_nearby":
                    out = {"status": "ok", "result": nearby(self._scout(), a.get("want"), a.get("rounds", 3))}
                elif name == "config_ble":
                    out = {"status": "ok", "result": config_ble(self._scout(), a["device"], a.get("wifi"),
                                                                a.get("password"), a.get("restore", False), a.get("mode"),
                                                                a.get("name"), a.get("room"))}
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
                out = {"status": "failed", "error": type(e).__name__, "message": str(e), "tool": name, "args": shown,
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
            out["observations"] = {} if name == "evidence" else self.obs.window(t0, t1)
            if self.run:
                shot = self.run.shot(jpg) if jpg else None
                ctxd = out.get("context") if out["status"] == "failed" else (
                    out.get("result") if name in ("screen", "tap", "back", "scroll", "open_app") else None)
                res = json.dumps(out.get("result", out.get("message")), ensure_ascii=False, default=str)
                self.run.step({"type": "tool", "case": case, "tool": name, "args": shown, "status": out["status"],
                               "ms": out["ms"], "result": res[:4000], "error": out.get("error"), "events": out["events"],
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
