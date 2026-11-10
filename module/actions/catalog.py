"""Danh mục hàm tương tác cho trang web (chuột phải vào node → chọn hàm → điền tham số → chạy).

feature: nhóm màn của hàm — "device" (màn chi tiết thiết bị), "timer", "share", "cycle", "history", "general_info".
         Chuột phải vào màn chi tiết → mọi hàm của thiết bị đó; vào màn của feature → hàm của feature đó.
at:      tiền tố node phải có trong map cho thiết bị (không có → loại thiết bị không có feature này).
needs:   control phải có ở màn chi tiết (vd press_mode) — loại thiết bị không có dòng đó thì không hiện.
params:  [{name, label, type, choices?, default?, required?, hint?}]
         type: str | int | bool (luôn truyền) | flag (chỉ truyền khi bật) | choice | list (phẩy hoặc ô chọn) |
         tri ("" = giữ nguyên, on/off → True/False)
"""
from __future__ import annotations

from .cycle import add_cycle, delete_cycle, edit_cycle, list_cycles
from .history import history
from .info import general_info
from .inputs import get_inputs, set_input_ac, set_input_dc
from .lock import MODES, get_lock, set_lock
from .neo import (BUTTONS, PRESS, STATE, get_neo, link_intermediate, set_button, set_button_scenes,
                  unlink_intermediate, unlink_target)
from .power import get_power, set_power
from .room import get_room, set_room
from .press import delete_quick_timer, get_press_mode, get_quick_timer, set_press_mode, set_quick_timer
from .share import PERMS, edit_share, share, shared_users, unshare
from .timer import ACTION, DAYS, KIND, REPEAT, add_timer, delete_timer, edit_timer, list_timers
from .ui import ActionError, Ui, node


def _shared(scout, device):
    scout.goto(node(scout, "share/list", device))
    return shared_users(Ui(scout))


def _input_ac(scout, device, on):
    return set_input_ac(scout, device, on == "on")


def _cycle_edit(scout, device, index=0, mode=None, **kw):
    return edit_cycle(scout, device, index, limit=None if mode is None else mode == "limit", **kw)


def P(name, label, type="str", **kw) -> dict:
    return {"name": name, "label": label, "type": type, **kw}


_TIMER_FORM = [
    P("action", "Hành động", "choice", choices=list(ACTION)),
    P("kind", "Loại", "choice", choices=list(KIND)),
    P("repeat", "Chế độ lặp", "choice", choices=list(REPEAT)),
    P("days", "Thứ (lặp tuần / mặt trời)", "list", choices=DAYS),
    P("monthday", "Ngày trong tháng", "int", hint="1–31"),
    P("last_day", "Ngày cuối tháng", "flag"),
    P("date", "Ngày (một lần)", hint="YYYY-MM-DD"),
]
_CYCLE_FORM = [
    P("start", "Bắt đầu", hint="HH:MM (giới hạn thời gian)"),
    P("end", "Kết thúc", hint="HH:MM"),
    P("weekly", "Lặp hàng tuần", "tri"),
    P("days", "Thứ", "list", choices=DAYS),
    P("date", "Ngày (tắt lặp tuần)", hint="YYYY-MM-DD"),
]

ACTIONS = [
    # ---- màn chi tiết thiết bị ----
    {"id": "power-get", "label": "Bật/tắt: đọc trạng thái", "feature": "device", "at": "infoDevice@", "fn": get_power,
     "params": []},
    {"id": "power-set", "label": "Bật/tắt: bấm công tắc ở màn chi tiết", "feature": "device", "at": "infoDevice@", "needs": "power",
     "fn": set_power, "danger": True, "params": [P("state", "Trạng thái", "choice", choices=["on", "off"], required=True)]},
    {"id": "room-get", "label": "Phòng: đọc", "feature": "device", "at": "infoDevice@", "needs": "room",
     "fn": get_room, "params": []},
    {"id": "room-set", "label": "Phòng: đổi", "feature": "device", "at": "infoDevice@", "needs": "room",
     "fn": set_room, "danger": True, "params": [P("room", "Phòng", required=True, hint="tên phòng trong nhà")]},
    {"id": "lock-get", "label": "Khoá công tắc: đọc", "feature": "device", "at": "infoDevice@", "needs": "lock",
     "fn": get_lock, "params": []},
    {"id": "lock-set", "label": "Khoá công tắc: đặt", "feature": "device", "at": "infoDevice@", "needs": "lock",
     "fn": set_lock, "danger": True, "params": [P("mode", "Chế độ", "choice", choices=list(MODES), required=True)]},
    {"id": "press-get", "label": "Nhấn nhả: đọc", "feature": "device", "at": "infoDevice@", "needs": "press_mode",
     "fn": get_press_mode, "params": []},
    {"id": "press-set", "label": "Nhấn nhả: đặt", "feature": "device", "at": "infoDevice@", "needs": "press_mode",
     "fn": set_press_mode, "danger": True,
     "params": [P("value", "Thời gian", required=True, default="00:00", hint="MM:SS, 00:00 = tắt")]},
    {"id": "quick-get", "label": "Hẹn giờ nhanh: đọc", "feature": "device", "at": "infoDevice@", "needs": "quick_timer",
     "fn": get_quick_timer, "params": []},
    {"id": "quick-set", "label": "Hẹn giờ nhanh: đặt", "feature": "device", "at": "infoDevice@", "needs": "quick_timer",
     "fn": set_quick_timer, "danger": True,
     "params": [P("minutes", "Sau (phút)", "int", required=True, default=2, hint="2–999"),
                P("action", "Hành động", "choice", choices=["on", "off"], default="on")]},
    {"id": "quick-delete", "label": "Hẹn giờ nhanh: xoá", "feature": "device", "at": "infoDevice@",
     "needs": "quick_timer", "fn": delete_quick_timer, "danger": True, "params": []},
    {"id": "inputs-get", "label": "Đầu vào AC/DC: đọc", "feature": "device", "at": "infoDevice@", "needs": "input_ac",
     "fn": get_inputs, "params": []},
    {"id": "input-ac-set", "label": "Đầu vào AC: bật/tắt", "feature": "device", "at": "infoDevice@",
     "needs": "input_ac", "fn": _input_ac, "danger": True,
     "params": [P("on", "Chế độ đầu vào AC", "choice", choices=["on", "off"], required=True)]},
    {"id": "input-dc-set", "label": "Đầu vào DC: hành động", "feature": "device", "at": "infoDevice@",
     "needs": "input_dc_green", "fn": set_input_dc, "danger": True,
     "params": [P("color", "Đầu vào", "choice", choices=["green", "red"], required=True),
                P("action", "Hành động", "choice", choices=["on", "off", "none"], required=True)]},
    # ---- hẹn giờ ----
    {"id": "timer-list", "label": "Hẹn giờ: danh sách", "feature": "timer", "at": "timer/list", "fn": list_timers,
     "params": []},
    {"id": "timer-add", "label": "Hẹn giờ: thêm", "feature": "timer", "at": "timer/add", "fn": add_timer,
     "danger": True,
     "params": [P("at", "Giờ", hint="HH:MM (trống = giờ mặc định của form)"),
                *[dict(p, default={"action": "on", "kind": "time", "repeat": "weekly"}.get(p["name"]))
                  for p in _TIMER_FORM],
                P("run_online", "Chạy sau khi thiết bị online", "bool", default=True),
                P("save", "Bấm Lưu lại", "bool", default=True)]},
    {"id": "timer-edit", "label": "Hẹn giờ: sửa", "feature": "timer", "at": "timer/list", "fn": edit_timer,
     "danger": True,
     "params": [P("existing", "Hẹn giờ đang có", required=True, hint="HH:MM | sunrise | sunset"),
                P("at", "Giờ mới", hint="HH:MM (trống = giữ)"), *_TIMER_FORM,
                P("run_online", "Chạy sau khi online", "tri")]},
    {"id": "timer-delete", "label": "Hẹn giờ: xoá", "feature": "timer", "at": "timer/list", "fn": delete_timer,
     "danger": True, "params": [P("at", "Hẹn giờ", required=True, hint="HH:MM | sunrise | sunset")]},
    # ---- chia sẻ ----
    {"id": "share-list", "label": "Chia sẻ: danh sách", "feature": "share", "at": "share/list", "fn": _shared,
     "params": []},
    {"id": "share", "label": "Chia sẻ: thêm người", "feature": "share", "at": "share/add", "fn": share, "danger": True,
     "params": [P("phone", "Số điện thoại", hint="điền 1 trong 2"), P("email", "Email"),
                P("perms", "Quyền (trống = mặc định)", "list", choices=list(PERMS)),
                P("submit", "Bấm Chia sẻ", "bool", default=True)]},
    {"id": "share-edit", "label": "Chia sẻ: sửa quyền", "feature": "share", "at": "share/list", "fn": edit_share,
     "danger": True,
     "params": [P("who", "Người được chia sẻ", required=True, hint="sđt hoặc email"),
                P("perms", "Quyền", "list", choices=list(PERMS), required=True)]},
    {"id": "unshare", "label": "Chia sẻ: xoá người", "feature": "share", "at": "share/list", "fn": unshare,
     "danger": True, "params": [P("who", "Người được chia sẻ", required=True, hint="sđt hoặc email")]},
    # ---- lặp tuần hoàn ----
    {"id": "cycle-list", "label": "Tuần hoàn: danh sách", "feature": "cycle", "at": "cycle/list", "fn": list_cycles,
     "params": []},
    {"id": "cycle-add", "label": "Tuần hoàn: thêm", "feature": "cycle", "at": "cycle/add", "fn": add_cycle,
     "danger": True,
     "params": [P("on", "Thời gian bật", default="00:01", hint="MM:SS"), P("off", "Thời gian tắt", default="00:01",
                                                                          hint="MM:SS"),
                *_CYCLE_FORM, P("save", "Bấm Lưu lại", "bool", default=True)]},
    {"id": "cycle-edit", "label": "Tuần hoàn: sửa", "feature": "cycle", "at": "cycle/list", "fn": _cycle_edit,
     "danger": True,
     "params": [P("index", "Dòng thứ", "int", default=0, hint="0 = dòng đầu"),
                P("on", "Thời gian bật", hint="MM:SS (trống = giữ)"), P("off", "Thời gian tắt", hint="MM:SS"),
                P("mode", "Chế độ", "choice", choices=["", "forever", "limit"]), *_CYCLE_FORM]},
    {"id": "cycle-delete", "label": "Tuần hoàn: xoá", "feature": "cycle", "at": "cycle/list", "fn": delete_cycle,
     "danger": True, "params": [P("index", "Dòng thứ", "int", default=0, hint="0 = dòng đầu")]},
    # ---- thông tin chung ----
    # ---- NeoR6 (scenario_sw6) ----
    {"id": "neo-get", "label": "NeoR6: trung gian + hành vi 6 nút", "feature": "device", "at": "linkIntermediate@",
     "fn": get_neo, "params": []},
    {"id": "neo-link", "label": "NeoR6: liên kết thiết bị trung gian", "feature": "device", "at": "linkIntermediate@",
     "fn": link_intermediate, "danger": True,
     "params": [P("host", "Thiết bị trung gian", required=True, hint="tên công tắc Wi-Fi trong danh sách")]},
    {"id": "neo-unlink", "label": "NeoR6: gỡ thiết bị trung gian", "feature": "device", "at": "linkIntermediate@",
     "fn": unlink_intermediate, "danger": True, "params": []},
    {"id": "neo-button-set", "label": "NeoR6: gán nút điều khiển thiết bị", "feature": "device", "at": "button.sun@",
     "fn": set_button, "danger": True,
     "params": [P("button", "Nút", "choice", choices=list(BUTTONS), required=True),
                P("press", "Kiểu nhấn", "choice", choices=list(PRESS), required=True),
                P("target", "Thiết bị đích", required=True, hint="tên thiết bị trong 'Chọn thiết bị'"),
                P("state", "Hành động", "choice", choices=list(STATE), required=True)]},
    {"id": "neo-button-scenes", "label": "NeoR6: gán nút chạy ngữ cảnh (rỗng = bỏ)", "feature": "device",
     "at": "button.sun@", "fn": set_button_scenes, "danger": True,
     "params": [P("button", "Nút", "choice", choices=list(BUTTONS), required=True),
                P("press", "Kiểu nhấn", "choice", choices=list(PRESS), required=True),
                P("scenes", "Ngữ cảnh chạy khi ấn", "list", hint="tên, phẩy ngăn cách; rỗng = bỏ hết")]},
    {"id": "neo-unlink-target", "label": "Gỡ NeoR6 khỏi thiết bị này (Liên kết công tắc ngữ cảnh)", "feature": "device",
     "at": "infoDevice@", "needs": "context_link", "fn": unlink_target, "danger": True,
     "params": [P("neo", "Tên NeoR6", required=True)]},
    {"id": "general-info", "label": "Thông tin chung: đọc", "feature": "general_info", "at": "general_info/",
     "fn": general_info, "params": []},
    # ---- lịch sử ----
    {"id": "history", "label": "Lịch sử: đọc", "feature": "history", "at": "history/", "fn": history,
     "params": [P("since", "Từ mốc", hint="HH:MM[:SS] hôm nay | YYYY-MM-DD HH:MM:SS — cuộn tới mốc; trống = phần đang thấy")]},
]
BY_ID = {a["id"]: a for a in ACTIONS}


def _device(node_id: str) -> str | None:
    return node_id[node_id.rindex("[") + 1:-1] if node_id.endswith("]") and "[" in node_id else None


def _feature(node_id: str) -> str:
    return "device" if node_id.startswith("infoDevice@") else node_id.split("/", 1)[0]


def available(scout, node_id: str) -> list[dict]:
    """Hàm chạy được từ node này (không chạm điện thoại) — bỏ `fn` để gửi lên web."""
    device = _device(node_id)
    if device is None or node_id not in scout.graph.nodes:
        return []
    try:
        info = scout.graph.nodes[node(scout, "infoDevice@", device)]
    except ActionError:
        return []
    feat, out = _feature(node_id), []
    for a in ACTIONS:
        if feat not in ("device", a["feature"]):
            continue
        try:
            node(scout, a["at"], device)
        except ActionError:
            continue
        if a.get("needs") and a["needs"] not in info.controls:
            continue
        out.append({k: v for k, v in a.items() if k != "fn"})
    return out


def _conv(p: dict, v):
    t = p["type"]
    if t in ("bool", "flag"):
        return bool(v)
    if v is None or (isinstance(v, str) and not v.strip()) or v == []:
        return None
    if t == "int":
        return int(v)
    if t == "list":
        return [x.strip() for x in v.split(",") if x.strip()] if isinstance(v, str) else list(v)
    if t == "tri":
        return v == "on"
    return v.strip() if isinstance(v, str) else v


def run(scout, action_id: str, node_id: str, params: dict):
    """Chạy hàm `action_id` cho thiết bị của node `node_id` với tham số từ form (chuỗi rỗng = không truyền)."""
    a, device = BY_ID.get(action_id), _device(node_id)
    if a is None or device is None:
        raise ActionError(f"không có hàm {action_id!r} cho {node_id!r}")
    kw = {}
    for p in a["params"]:
        v = _conv(p, params.get(p["name"], p.get("default")))
        if p["type"] == "flag" and not v:
            continue
        if v is None:
            if p.get("required"):
                raise ActionError(f"thiếu {p['label']}")
            continue
        kw[p["name"]] = v
    return a["fn"](scout, device, **kw)
