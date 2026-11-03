"""Luật hold lấy từ code app 4.0.19 — sang bản app mới phải đối chiếu lại.

Nguồn: shared/logic/931_AreEqualItemDeviceForMemo.js:99–177 (onLongPressDevice),
nhóm loại ở core/utils/logic/798_FunctionCustom.js,
điều kiện trước ở shared/components/2785_TextNameDevice.js:1478.
"""
from __future__ import annotations

import copy
import logging

from .house import Device

log = logging.getLogger(__name__)

HOLD_WHEN = "block_control == 0 and blocked == 0"

DOOR = {"sdoor", "sdoor2", "sdoor3", "sdoor4", "sdoor5", "sdoor6", "sdoor7", "sdoor8", "sdoor9",
        "sdoor10", "sdoor11", "sdoor12", "sdoor13", "sdoor14", "sdoorbox", "GACHsdoor1"}
GATE_HUN = {"gatehun", "gatehuwf", "gatehuv2", "gatehuwfv2"}
GATE = {"gate", "gatev2", "wsgate"} | GATE_HUN
FAN_OEM = {"fanac", "fanacir", "fanacv2", "fandc", "faniracv2", "fanproacv2"}


def hold_allowed(d: Device) -> bool:
    """Hold có dẫn sang màn khác không (không bị popup chặn / luồng kích hoạt)."""
    return d.block_control == 0 and d.blocked == 0


def entry_route(root_type: str) -> str | None:
    """Route của màn đầu tiên khi hold ô thiết bị. None = không có cạnh hold / chưa rõ."""
    if root_type == "camera":
        return "DetailCamera"
    if root_type == "camera2v":
        return None                              # onLongPressDevice không điều hướng
    if root_type in DOOR:
        return "doorScreen"                      # getKeyNameNavigationDoor, khi device.pass rỗng
    if root_type in GATE:
        return "GateHunControl" if root_type in GATE_HUN else "GateControlScreen"
    if root_type == "slock":
        return None                              # TODO: tra nhánh slock trong _onPressControlDevice
    if root_type in ("thswifi", "GACHths"):
        return "KEY_SENSOR_FISRT_SCREEN"
    if root_type == "GACHLedHT":
        return "KEY_LED_HT_CONTROLL_SCREEN"
    if root_type in FAN_OEM:
        return "KEY_NAV_FAN_SCREEN"
    if root_type == "CAMERA_RS":
        return None                              # giống tap (onPressDevice) — chưa tra
    # isTypeDriverLed → KEY_DRIVER_LED_CONTROL_SCREEN / infoDevice theo index_in_root: chưa tách
    return "infoDevice"


# Anchor dùng chung theo route của màn vào. infoDevice: title = useDeviceNameAppBar(device.name,
# translate("detailDevice")) — "Chi tiết thiết bị" ở đầu trang, tên thiết bị khi cuộn
# (4178_InfoDeviceRoute.js:1125, kiểm trên SK01 ngày 2026-10-27).
LEAF_TEMPLATES = {
    "infoDevice": {
        "anchor": {"any": [{"key": "detailDevice"}, {"text": "{device.name}"}]},
        "anchors": [["detailDevice", "renameDevice"]],
        "check": "{device.name}",
    },
}


def leaf_doc(root_type: str) -> dict | None:
    """Pattern tối thiểu TRONG BỘ NHỚ (không ghi file) cho root_type chưa có root_type/<rt>.json:
    chỉ màn vào khi hold + cạnh back. Route đã có template thì có anchor → đi vào được ngay;
    chưa có thì node "chưa khám" (plan bỏ qua). None = loại này không có cạnh hold."""
    route = entry_route(root_type)
    if route is None:
        log.info("%s: không có cạnh hold hoặc chưa rõ route → không sinh leaf", root_type)
        return None
    node = {"route": route, "param": "device", "anchors": [], **copy.deepcopy(LEAF_TEMPLATES.get(route, {}))}
    node["controls"] = {"back": {"gesture": "back", "kind": "nav", "to": "@back"}}
    return {"root_type": root_type, "status": "leaf", "source": "931:onLongPressDevice",
            "entry": route, "nodes": {route: node}}
