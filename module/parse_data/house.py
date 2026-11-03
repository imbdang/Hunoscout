"""Response → House: chỉ chép các trường cần cho test (danh sách trắng)."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .source import DataError


@dataclass(slots=True)
class Device:
    id: str
    name: str                 # duy nhất trong nhà (đảm bảo từ phía dev)
    root_type: str            # khoá chọn sub-map
    type: str                 # nhóm thô: switch, mos, sdoor...
    root_id: str
    index_in_root: int
    room_id: str
    room_name: str
    block_control: int        # 1/2/3 → hold bật popup, không vào chi tiết
    blocked: int              # 1 → hold vào luồng kích hoạt
    active: int
    suggest: int              # 1 → nằm trong "Thiết bị hay dùng" ở Home
    index_suggest: int
    index_in_room: int
    last_online: str | None
    # Số liên kết — dòng tương ứng trên màn thiết bị chỉ hiện khi > 0 (useNeoLogic / useSt02Logic)
    neo_links: int = 0        # len(data_extra.neoLinks): công tắc ngữ cảnh (neo R6) đã liên kết
    st02_links: int = 0       # len(data_extra.listSt02Linked): cảm biến cầu thang ST02 đã liên kết


@dataclass(slots=True)
class Room:
    id: str
    name: str
    index: int
    default: int              # 1 = phòng mặc định ("Chưa xếp phòng")
    hidden: int


@dataclass(slots=True)
class House:
    home_id: str
    name: str                 # tên nhà — title của Home
    observed_at: str
    rooms: list[Room]
    devices: dict[str, Device]                          # name → Device
    duplicates: list[str] = field(default_factory=list)  # tên trùng, đã loại khỏi devices

    @property
    def root_types(self) -> set[str]:
        return {d.root_type for d in self.devices.values()}


@dataclass(slots=True)
class HouseDiff:
    added: list[str] = field(default_factory=list)            # tên
    removed: list[str] = field(default_factory=list)
    renamed: list[tuple[str, str]] = field(default_factory=list)
    moved_room: list[str] = field(default_factory=list)
    new_root_types: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return any((self.added, self.removed, self.renamed, self.moved_room, self.new_root_types))


def _int(v) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def parse_house(resp: dict, home_id: str, observed_at: str) -> House:
    homes = {str(h.get("id")): h for h in resp["data"]}
    if home_id not in homes:
        raise DataError(f"không có nhà {home_id} trong response; có: {', '.join(homes)}")
    h = homes[home_id]

    rooms: list[Room] = []
    devices: dict[str, Device] = {}
    dup: set[str] = set()
    for r in h.get("rooms") or []:
        rooms.append(Room(
            id=str(r["id"]), name=r["name"], index=_int(r.get("index")),
            default=_int(r.get("default_room")), hidden=_int(r.get("is_hidden")),
        ))
        for d in r.get("devices") or []:
            extra = d.get("data_extra") if isinstance(d.get("data_extra"), dict) else {}   # thiết bị không có thì là ""
            dev = Device(
                id=str(d["id"]), name=d["name"], root_type=d["root_type"], type=d.get("type") or "",
                root_id=d.get("root_id") or "", index_in_root=_int(d.get("index_in_root")),
                room_id=str(r["id"]), room_name=d.get("room_name") or r["name"],
                block_control=_int(d.get("block_control")), blocked=_int(d.get("blocked")),
                active=_int(d.get("active")), suggest=_int(d.get("suggest")),
                index_suggest=_int(d.get("index_suggest")), index_in_room=_int(d.get("index_in_room")),
                last_online=d.get("last_online"),
                neo_links=len(extra.get("neoLinks") or {}), st02_links=len(extra.get("listSt02Linked") or []),
            )
            if dev.name in devices:
                dup.add(dev.name)
            devices.setdefault(dev.name, dev)
    # Tên trùng thì không biết ô nào là ô nào → loại hẳn, không bao giờ chạm vào
    for name in dup:
        devices.pop(name)
    rooms.sort(key=lambda r: r.index)
    return House(home_id, h.get("name") or "", observed_at, rooms, devices, sorted(dup))


def save_house(house: House, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(house), ensure_ascii=False, indent=2), encoding="utf-8")


def load_house(path: Path) -> House | None:
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    return House(
        home_id=raw["home_id"], name=raw.get("name", ""), observed_at=raw["observed_at"],
        rooms=[Room(**r) for r in raw["rooms"]],
        devices={k: Device(**v) for k, v in raw["devices"].items()},
        duplicates=raw.get("duplicates", []),
    )


def diff_house(old: House | None, new: House) -> HouseDiff:
    """So theo Device.id (không theo tên) để nhận ra đổi tên / chuyển phòng."""
    diff = HouseDiff()
    if old is None:
        diff.added = sorted(new.devices)
        diff.new_root_types = sorted(new.root_types)
        return diff
    before = {d.id: d for d in old.devices.values()}
    after = {d.id: d for d in new.devices.values()}
    diff.added = sorted(after[i].name for i in after.keys() - before.keys())
    diff.removed = sorted(before[i].name for i in before.keys() - after.keys())
    for i in after.keys() & before.keys():
        if before[i].name != after[i].name:
            diff.renamed.append((before[i].name, after[i].name))
        if before[i].room_id != after[i].room_id:
            diff.moved_room.append(after[i].name)
    diff.new_root_types = sorted(new.root_types - old.root_types)
    return diff
