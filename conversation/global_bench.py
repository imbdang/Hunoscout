"""Kịch bản test toàn cục: route khắp map + chạy mọi hàm tương tác (ghi xong trả lại), đo nghẽn.
Đo: từng bước route (pha tìm / thao tác / chờ màn / yên / mù), thời gian riêng từng hàm Ui, từng RPC uiautomator2,
từng lệnh adb (subprocess), từng lần ngủ cứng (theo chỗ gọi). Ghi raw JSON để phân tích.

ANDROID_SERIAL=2fc3878f PYTHONPATH=. .venv/bin/python conversation/global_bench.py conversation/bench-<ngày>.json
.venv/bin/python conversation/bench_report.py conversation/bench-<ngày>.json      # in bảng tổng hợp
Ghi thay đổi thật lên thiết bị dev (khoá, hẹn giờ, tuần hoàn…) rồi trả lại; chia sẻ cần imbdang@gmail.com đang được chia sẻ.
"""
import collections
import json
import logging
import re
import subprocess
import sys
import time

from uiautomator2.core import BasicUiautomatorServer

import module.interact.u2  # noqa: F401  (vá jsonrpc_call trước, rồi mới bọc đo)
from module.actions import catalog
from module.actions import ui as UI
from module.scout import Scout

OUT = sys.argv[1]
SEG = ["khởi động"]
rpc = collections.defaultdict(lambda: [0, 0.0])          # (seg, method)
sleeps = collections.defaultdict(lambda: [0, 0.0])       # (seg, chỗ gọi)
adbc = collections.defaultdict(lambda: [0, 0.0])         # (seg, lệnh)
uiex = collections.defaultdict(lambda: [0, 0.0])         # (seg, hàm Ui) thời gian riêng (trừ hàm Ui con)
steps, segs = [], []

_rpc = BasicUiautomatorServer.jsonrpc_call
def rpc_wrap(self, method, params=None, timeout=10):
    t = time.monotonic()
    try:
        return _rpc(self, method, params, timeout)
    finally:
        r = rpc[(SEG[0], method)]; r[0] += 1; r[1] += time.monotonic() - t
BasicUiautomatorServer.jsonrpc_call = rpc_wrap

_sleep = time.sleep
def sleep_wrap(x):
    f = sys._getframe(1)
    k = (SEG[0], f"{f.f_code.co_filename.rsplit('/', 1)[-1]}:{f.f_code.co_name}")
    sleeps[k][0] += 1; sleeps[k][1] += x
    _sleep(x)
time.sleep = sleep_wrap

_run = subprocess.run
def run_wrap(cmd, *a, **k):
    t = time.monotonic()
    try:
        return _run(cmd, *a, **k)
    finally:
        parts = cmd if isinstance(cmd, list) else [str(cmd)]
        name = " ".join(p for p in parts[3:6] if not p.startswith("-"))[:40] if parts[:1] == ["adb"] else str(parts[0])
        r = adbc[(SEG[0], name)]; r[0] += 1; r[1] += time.monotonic() - t
subprocess.run = run_wrap

stack = []
def timed(owner, name, label=None):
    f = getattr(owner, name); label = label or name
    def g(*a, **k):
        t = time.monotonic(); stack.append([label, 0.0])
        try:
            return f(*a, **k)
        finally:
            dt = time.monotonic() - t; _, child = stack.pop()
            e = uiex[(SEG[0], label)]; e[0] += 1; e[1] += dt - child
            if stack:
                stack[-1][1] += dt
    setattr(owner, name, g)
for n in ("set_wheel", "pick", "reach", "elements", "need", "find", "settled", "gone", "green", "fill", "tap",
          "drag", "scroll_up", "reveal", "pick_number", "hide_keyboard"):
    timed(UI.Ui, n)

logging.basicConfig(level=logging.WARNING)
s = Scout()
t0 = time.monotonic(); s.start(fresh=False); segs.append({"seg": "khởi động", "s": time.monotonic() - t0, "err": None})
timed(s, "goto", "goto (route)")

def on_move(e, how, ms):
    head = how.split("|")[0].strip()
    ph = {k: float(v) for k, v in re.findall(r"(tìm|tap|back|hold|chờ màn|yên|nghỉ) ([\d.]+)", how)}
    steps.append({"seg": SEG[0], "src": e.src, "to": e.to, "g": e.action.gesture, "ms": ms, "how": head, "ph": ph})
s.nav.on_move = on_move

CT, ATM = "infoDevice@swinputv2[Công tắc ]", "infoDevice@atmwifiv2[Aptomat]"
def A(aid, node=CT, **params):
    return lambda: catalog.run(s, aid, node, params)
def G(dst):
    return lambda: s.goto(dst)

state = {}
def cycle_idx(marker):
    items = catalog.run(s, "cycle-list", CT, {})
    return next(i for i, d in enumerate(items) if marker in d)

SCENARIO = [
    ("route: → home", G("home")),
    ("route: home → chi tiết Công tắc", G(CT)),
    ("khoá: đọc", A("lock-get")),
    ("khoá: đặt app", A("lock-set", mode="app")),
    ("khoá: trả both", A("lock-set", mode="both")),
    ("nhấn nhả: đọc", A("press-get")),
    ("nhấn nhả: đặt 00:05", A("press-set", value="00:05")),
    ("nhấn nhả: trả 00:00", A("press-set", value="00:00")),
    ("hẹn giờ nhanh: đọc", A("quick-get")),
    ("hẹn giờ nhanh: đặt 3 phút tắt", A("quick-set", minutes=3, action="off")),
    ("hẹn giờ nhanh: xoá", A("quick-delete")),
    ("đầu vào: đọc", A("inputs-get")),
    ("đầu vào AC: bật", A("input-ac-set", on="on")),
    ("đầu vào AC: trả tắt", A("input-ac-set", on="off")),
    ("đầu vào DC xanh: bật", A("input-dc-set", color="green", action="on")),
    ("đầu vào DC xanh: trả none", A("input-dc-set", color="green", action="none")),
    ("hẹn giờ: danh sách", A("timer-list")),
    ("hẹn giờ: thêm 05:55 tắt T2,T6", A("timer-add", at="05:55", action="off", kind="time", repeat="weekly",
                                        days="mon,fri", run_online=True, save=True)),
    ("hẹn giờ: sửa 05:55 → 05:57", A("timer-edit", existing="05:55", at="05:57")),
    ("hẹn giờ: xoá 05:57", A("timer-delete", at="05:57")),
    ("tuần hoàn: danh sách", A("cycle-list")),
    ("tuần hoàn: thêm 00:20/00:10", A("cycle-add", on="00:20", off="00:10", save=True)),
    ("tuần hoàn: sửa tắt 00:15", lambda: catalog.run(s, "cycle-edit", CT, {"index": cycle_idx("bật 00:20 | Thời gian tắt 00:10"), "off": "00:15"})),
    ("tuần hoàn: xoá", lambda: catalog.run(s, "cycle-delete", CT, {"index": cycle_idx("bật 00:20 | Thời gian tắt 00:15")})),
    ("chia sẻ: danh sách", A("share-list")),
    ("chia sẻ: sửa quyền +timer", A("share-edit", who="imbdang@gmail.com", perms="control,history,timer")),
    ("chia sẻ: trả quyền", A("share-edit", who="imbdang@gmail.com", perms="control,history")),
    ("lịch sử: đọc", A("history")),
    ("thông tin chung Công tắc: đọc", A("general-info")),
    ("route: → home", G("home")),
    ("route: home → chi tiết Aptomat", G(ATM)),
    ("thông tin chung Aptomat: đọc", A("general-info", node=ATM)),
    ("route: → chi tiết Chống giật 4", G("infoDevice@GACHshock[Chống giật 4]")),
    ("route: → chi tiết Homekit", G("infoDevice@gatewayv3[Thiết bị trung tâm Homekit]")),
    ("route: → chi tiết Công tắc", G(CT)),
    ("route: → share/add (sâu)", G("share/add[Công tắc ]")),
    ("route: share/add → home", G("home")),
]

for label, fn in SCENARIO:
    SEG[0] = label
    t = time.monotonic(); err = None; out = None
    try:
        out = fn()
    except Exception as ex:                      # ghi lỗi, cho goto sau nhận diện lại
        err = f"{type(ex).__name__}: {ex}"
        s.nav.cur = None
    dt = time.monotonic() - t
    segs.append({"seg": label, "s": dt, "err": err, "out": out if isinstance(out, (str, bool, int, type(None))) else None})
    print(f"{label:38s} {dt:6.2f}s {'LỖI ' + err if err else ''}", flush=True)

json.dump({"segs": segs, "steps": steps,
           "rpc": [[k[0], k[1], v[0], v[1]] for k, v in rpc.items()],
           "sleeps": [[k[0], k[1], v[0], v[1]] for k, v in sleeps.items()],
           "adb": [[k[0], k[1], v[0], v[1]] for k, v in adbc.items()],
           "ui": [[k[0], k[1], v[0], v[1]] for k, v in uiex.items()]},
          open(OUT, "w"), ensure_ascii=False, indent=1)
print("xong", sum(x["s"] for x in segs))
