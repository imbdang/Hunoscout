"""Chia sẻ thiết bị (màn share/add): tab Số điện thoại | Email → điền thẳng vào ô (set_text) → app tự tra tài khoản
("Không tìm thấy tài khoản!" nếu không có) → chọn quyền (✓ xanh = đang chọn) → nút Chia sẻ.

Quyền có trên form tuỳ loại thiết bị → ghi sẵn ở root_type/<rt>.json "share.perms" (theo Wallpad
docs/device/feature/share/<rt>.md): chỉ tìm đúng các dòng đó, một lần dump, không dò cả 7 key.
"""
from __future__ import annotations

import json
import re
import time

from .. import config
from .ui import ActionError, Ui, arrive, node

PERMS = {"control": "controlDeviceText", "timer": "fullPermissionAlarmText", "collection": "permissionCollectionText",
         "basic": "permissionSettingBasicText", "advanced": "permissionSettingAdvancedText",
         "history": "permissionViewHistoryText", "notify_offline": "permissionNotifyDeviceOfflineText"}
NOT_FOUND = "Không tìm thấy tài khoản"           # chữ viết cứng trong app (không có trong bảng i18n)


def device_perms(scout, device: str) -> list[str]:
    """Quyền chia sẻ của loại thiết bị (root_type/<rt>.json "share.perms"); chưa ghi thì dùng cả 7."""
    rt = node(scout, "infoDevice@", device).split("@", 1)[1].split("[", 1)[0]
    p = config.PATTERN_DIR / "root_type" / f"{rt}.json"
    perms = json.loads(p.read_text(encoding="utf-8")).get("share", {}).get("perms") if p.exists() else None
    return perms or list(PERMS)


def _check(names: list[str], perms: list[str]) -> None:
    if set(perms) - set(names):
        raise ActionError(f"perms phải thuộc {names}")


def _perm_boxes(ui: Ui, names: list[str]) -> dict[str, tuple[int, int, int, int]]:
    """Khung dấu ✓ ở cuối mỗi dòng quyền `names` đang thấy trên màn (một lần dump)."""
    rx = {n: re.compile(ui.row_sel(key=PERMS[n])["descriptionMatches"]) for n in names}
    out = {}
    for e in ui.elements():
        for n, r in rx.items():
            if n not in out and e.clickable and r.match(e.desc):
                cy = (e.bounds[1] + e.bounds[3]) // 2
                out[n] = (e.bounds[2] - 130, cy - 40, e.bounds[2] - 30, cy + 40)
    return out


def permissions(ui: Ui, names: list[str]) -> set[str]:
    boxes = _perm_boxes(ui, names)
    return {n for n, on in zip(boxes, ui.green(list(boxes.values()))) if on}


def share(scout, device: str, phone: str | None = None, email: str | None = None,
          perms: list[str] | None = None, submit: bool = True) -> dict:
    """Điền người nhận + quyền; submit=True thì bấm Chia sẻ. → {"found", "perms", "shared"}."""
    if bool(phone) == bool(email):
        raise ActionError("cần đúng một trong phone / email")
    names = device_perms(scout, device)
    if perms is not None:
        _check(names, perms)
    add, lst = node(scout, "share/add", device), node(scout, "share/list", device)
    scout.goto(add)
    ui = Ui(scout)
    ui.tap(ui.need(ui.text_sel(key="email" if email else "phone"), "tab Email / Số điện thoại"))
    time.sleep(0.4)
    ui.fill(email or phone)
    not_found = ui.find({"textStartsWith": NOT_FOUND}, 4.0) is not None
    result = {"found": not not_found}
    if perms is not None:
        _set_perms(ui, perms, names)
    result["perms"] = sorted(permissions(ui, names))
    if not submit or not_found:
        result["shared"] = False
        return result
    ui.tap(ui.need(ui.text_sel(key="share"), "nút Chia sẻ"))
    # app KHÔNG tự về danh sách: ở lại form, xoá ô nhập, hiện người vừa chia sẻ ở "Đề xuất chia sẻ"
    if not ui.find(ui.text_sel(key="enterEmail" if email else "enterPhoneNumberShare"), 6.0):
        raise ActionError("bấm Chia sẻ nhưng form không xoá ô nhập (chia sẻ lỗi?)")
    scout.goto(lst)
    who = email or phone
    if not ui.find({"textContains": who}, 4.0):
        raise ActionError(f"đã chia sẻ nhưng danh sách không có {who}")
    result["shared"] = True
    result["users"] = shared_users(ui)
    return result


def shared_users(ui: Ui) -> list[str]:
    """Dòng phụ dưới tên người được chia sẻ → "<sđt|email> - <quyền>". App ghi sđt là "0396674953 - Tùy chỉnh",
    email là "imbdang@gmail.com\nTùy chỉnh"."""
    return [" - ".join(p.strip() for p in re.split(r" - |\n", e.text.strip(), maxsplit=1))
            for e in ui.elements() if e.bounds[1] > 450 and (" - " in e.text or "\n" in e.text.strip())]


def _row_y(ui: Ui, who: str) -> int:
    """Tâm dọc dòng người được chia sẻ (dòng tên + dòng "<who> - <quyền>"); icon ✏️/🗑 không có trong cây UI."""
    sub = ui.need({"textStartsWith": who}, f"người được chia sẻ {who}")
    return sub[1] - 12


def _set_perms(ui: Ui, perms: list[str], names: list[str]) -> None:
    want = set(perms)
    _check(names, perms)
    boxes = _perm_boxes(ui, names)
    if len(boxes) != len(names):
        raise ActionError(f"không thấy dòng quyền {sorted(set(names) - set(boxes))}")
    for name, on in zip(boxes, ui.green(list(boxes.values()))):
        if (name in want) != on:
            ui.tap(boxes[name])         # ô ✓ nằm trong dòng bấm được, toạ độ có sẵn từ dump
            time.sleep(0.3)
    got = permissions(ui, names)
    if got != want:
        raise ActionError(f"chọn quyền {sorted(want)} nhưng đang chọn {sorted(got)}")


def edit_share(scout, device: str, who: str, perms: list[str]) -> dict:
    """Sửa quyền của người đã được chia sẻ (sđt/email `who`): ✏️ → hộp thoại Chỉnh sửa quyền → Lưu lại."""
    names = device_perms(scout, device)
    _check(names, perms)
    scout.goto(node(scout, "share/list", device))
    ui = Ui(scout)
    ui.d.click(ui.d.window_size()[0] - 305, _row_y(ui, who))
    ui.need(ui.text_sel(key="editPermissionHeaderText"), "hộp thoại Chỉnh sửa quyền")
    _set_perms(ui, perms, names)
    ui.tap(ui.need(ui.option_sel(key="save"), "nút Lưu lại"))
    if not ui.gone(ui.text_sel(key="editPermissionHeaderText"), 5.0):
        raise ActionError("bấm Lưu lại nhưng hộp thoại Chỉnh sửa quyền không đóng")
    time.sleep(0.6)
    return {"users": shared_users(ui)}


def unshare(scout, device: str, who: str) -> dict:
    """Ngừng chia sẻ cho `who`: 🗑 → hộp thoại "Xoá chia sẻ" → Xoá."""
    scout.goto(node(scout, "share/list", device))
    ui = Ui(scout)
    ui.d.click(ui.d.window_size()[0] - 174, _row_y(ui, who))
    ui.need(ui.text_sel(key="deleteSharedDevice"), "hộp thoại Xoá chia sẻ")
    ui.pick("delete", what="nút Xoá")
    if not ui.gone({"textStartsWith": who}, 6.0):
        raise ActionError(f"bấm Xoá nhưng {who} vẫn trong danh sách")
    return {"users": shared_users(ui)}
