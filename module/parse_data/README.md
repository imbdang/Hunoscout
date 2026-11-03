# parse_data

Đọc response danh sách nhà/thiết bị (do hook REST ghi ra) → dữ liệu nhà gọn, sạch cho IDLE,
và tạo khung `<root_type>.json` cho loại thiết bị chưa có pattern.

Không thao tác điện thoại, không biết gì về graph. Chỉ đọc file → trả về struct → ghi file.

## Vị trí trong state machine

```
scout.py — IDLE
  1. resp, observed_at = latest_response(EXPORTS)      ← parse_data
  2. check_fresh(observed_at)                           ← parse_data
  3. house = parse_house(resp, HOME_ID)                 ← parse_data
  4. diff_house(load_house(...), house); save_house()   ← parse_data
  5. for rt in house.root_types: ensure_stub(rt)        ← parse_data
  6. pattern = load_pattern(house)                      ← ui_map
  7. missing = plan(pattern, resolved, profile)         ← ui_map
  8. missing → DISCOVERY, rỗng → ACTIVE                 ← scout
```

## Nguồn dữ liệu

Hook REST trong `~/Reverse/HunonicApp/mitm/` (xem `README-direct.md` ở đó):
APK 4.0.19 đã vá, `NetworkingModule` của RN gọi `qa.hunonic.RestCapture` → logcat
tag `HUNONIC_REST_QA` → `scripts/collect-direct.py` ghép lại thành file.

| File | Dùng |
|---|---|
| `exports/latest-homes-devices-response.json` | response gốc, nguồn chính |
| `exports/latest-home-device-inventory.json` | có `observed_at` (lúc máy tính ghi nhận) → kiểm tra độ mới |

Giới hạn cần nhớ:
- Chỉ REST, **không có MQTT** → trạng thái bật/tắt có thể cũ hơn màn hình. Chỉ so các trường REST
  (tên, phòng, block_control…) hoặc kéo tải lại màn trước khi so.
- Collector phải chạy (`direct-capture.py start`) **trước** khi app tải danh sách, nếu không logcat rơi mảnh.
- Hook gắn với APK 4.0.19 đã vá; cài bản chính thức là mất hook.

Cấu hình (không viết cứng trong code):

```python
EXPORTS = "~/Reverse/HunonicApp/mitm/exports"
HOME_ID = "792334"          # chỉ test 1 nhà
MAX_AGE = timedelta(hours=12)
```

## Cấu trúc response (đã kiểm trên capture thật)

```
{status, message, data: [home], secure_sign}          ← bỏ secure_sign
home   {id, name, rooms: [room], header_data, ...}     ← 4 nhà, chỉ 792334 có thiết bị
room   {id, name, index, is_hidden, devices: [device]}
device {id, name, root_id, root_type, type, index_in_root, room_id, room_name,
        block_control, blocked, active, state, value, last_online, ...  (≈55 trường)}
```

- Kiểu lẫn lộn: phần lớn là chuỗi (`"0"`, `"1"`), riêng `blocked` là int → chuẩn hoá về `int`.
- Một `root_id` có thể có nhiều mục (nhiều nút/kênh, phân biệt bằng `index_in_root`).
  Mỗi mục là một ô trên app. Nhà hiện tại: 12 mục, 12 root.
- **Trường nhạy cảm — tuyệt đối không chép sang hunoscout:** `key`, `iv`, `topicpub`, `topicsub`,
  số điện thoại / tên chủ nhà ở cấp home, toàn bộ `secure_sign`. Dùng danh sách trắng, không dùng danh sách đen.

## Struct

```python
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
    suggest: int              # 1 → nằm trong "Thiết bị hay dùng" (equipmentUsed) ở Home
    index_suggest: int        # thứ tự trong mục đó
    index_in_room: int
    last_online: str | None

@dataclass(slots=True)
class Room:
    id: str
    name: str
    index: int
    default: int              # 1 = phòng mặc định "Chưa xếp phòng" (default_room)
    hidden: int

@dataclass(slots=True)
class House:
    home_id: str
    observed_at: str          # ISO, lấy từ inventory
    rooms: list[Room]
    devices: dict[str, Device]        # name → Device (tên duy nhất)
    duplicates: list[str]             # tên trùng, đã loại khỏi devices

    @property
    def root_types(self) -> set[str]: ...
```

## Function

### `source.py`

```python
def latest_response(exports: Path) -> tuple[dict, datetime]
```
Đọc `latest-homes-devices-response.json`; lấy `observed_at` từ inventory (thiếu thì dùng mtime file).
Lỗi rõ ràng nếu file không có / `status` không phải `true` / thiếu `data`.

```python
def check_fresh(observed_at: datetime, max_age: timedelta) -> str | None
```
Trả về câu cảnh báo nếu dữ liệu cũ hơn `max_age` (gợi ý: mở app, tải lại danh sách, `export` lại). Không raise.

### `house.py`

```python
def parse_house(resp: dict, home_id: str) -> House
```
1. Tìm home có `id == home_id` trong `resp["data"]`; không có → lỗi kèm danh sách id có sẵn.
2. Duyệt `rooms[].devices[]`, chép **chỉ** các trường của `Device`, ép kiểu số.
3. Gom vào `devices` theo `name`. Tên trùng → **loại hẳn** cả các thiết bị cùng tên khỏi `devices`, ghi vào
   `duplicates` (vi phạm giả định → không bao giờ chạm vào, phần còn lại của nhà vẫn chạy được).
   Capture 2026-10-25 còn hai "Ổ cắm" (`sswitch2v`, `sk02wifi`) nên hiện chỉ có 10/12 thiết bị trong map.

```python
def save_house(house: House, path: Path) -> None     # data/<serial>/house.json
def load_house(path: Path) -> House | None
```

```python
def diff_house(old: House | None, new: House) -> HouseDiff
```
So theo `Device.id` (không theo tên): `added`, `removed`, `renamed`, `moved_room`, `new_root_types`.
- `new_root_types` → cần stub + DISCOVERY phần thiết bị đó.
- `renamed` / `moved_room` → xoá toạ độ cạnh động của thiết bị đó trong `data/<serial>/huno_pattern/`.

### `rules.py` — luật hold lấy từ code app

Nguồn: `shared/logic/931_AreEqualItemDeviceForMemo.js:99–177` (`onLongPressDevice`),
nhóm loại ở `core/utils/logic/798_FunctionCustom.js`, điều kiện trước ở
`shared/components/2785_TextNameDevice.js:1478`.

```python
def hold_allowed(d: Device) -> bool
```
`block_control == 0 and blocked == 0`. Ngược lại hold mở popup / luồng kích hoạt → không phải cạnh điều hướng.
Biểu diễn trong pattern bằng `"when": "block_control == 0 and blocked == 0"`.

```python
def entry_route(root_type: str, index_in_root: int = 1) -> str | None
```
Màn đầu tiên khi hold ô thiết bị ở Home. `None` = không có cạnh hold.

| Điều kiện (theo thứ tự trong code) | Route |
|---|---|
| `camera` | `DetailCamera` |
| `camera2v` | `None` — không có cạnh hold |
| `isTypeDoor` (`sdoor`…`sdoor14`, `sdoorbox`, `GACHsdoor1`) | `doorScreen` (`passwordDoor` nếu `device.pass`) |
| `isTypeGate` (`gate`, `gatev2`, `wsgate`, `gatehun*`) | `GateControlScreen` / `GateHunControl` (`passwordDoor` nếu `device.pass`) |
| `slock` | giống tap (`_onPressControlDevice`) — chưa tra, chưa tạo stub |
| `thswifi`, `GACHths` | `KEY_SENSOR_FISRT_SCREEN` |
| `isTypeDriverLed` | `KEY_DRIVER_LED_CONTROL_SCREEN`, hoặc `infoDevice` khi gộp đèn (phụ thuộc `index_in_root`) |
| `GACHLedHT` | `KEY_LED_HT_CONTROLL_SCREEN` |
| `isTypeFanOem` (`fanac`, `fanacir`, `fanacv2`, `fandc`, `faniracv2`, `fanproacv2`) | `KEY_NAV_FAN_SCREEN` |
| `CAMERA_RS` | giống tap (`onPressDevice`) |
| còn lại | `infoDevice` |

Áp vào nhà 792334:

| root_type | Route khi hold |
|---|---|
| `sswitch2v`, `sk02wifi`, `GACHshock` (nhóm `isTypeRenderSwitch`) | `infoDevice` |
| `sdoor8` | màn điều khiển cửa |
| `thswifi` | `KEY_SENSOR_FISRT_SCREEN` |
| `stair_sensor`, `GACHmosv2`, `gatewayv3`, `voiceboxv1`, `atmwifiv2`, `irwifiv2`, `irchildv2` | `infoDevice` |

Bảng này chép tay từ bản decompile 4.0.19. Sang bản app mới phải đối chiếu lại `onLongPressDevice`.

```python
def ensure_stub(root_type: str, pattern_dir: Path) -> Path | None
```
Nếu `data/huno_pattern/<root_type>.json` chưa có → tạo khung từ `entry_route`. Đã có → không đụng.
`entry_route` trả `None` → không tạo, ghi log.

Khung sinh ra (ví dụ `thswifi`):

```json
{
  "root_type": "thswifi",
  "status": "stub",
  "source": "931:onLongPressDevice",
  "entry": "KEY_SENSOR_FISRT_SCREEN@thswifi",
  "nodes": {
    "KEY_SENSOR_FISRT_SCREEN@thswifi": {
      "route": "KEY_SENSOR_FISRT_SCREEN",
      "param": "device",
      "anchors": [],
      "check": "{device.name}",
      "edges": [{"to": "@back", "action": {"gesture": "back"}}]
    }
  }
}
```

- Cạnh **đi vào** màn thiết bị không nằm trong stub mà ở placeholder của `core.json`
  (`home` → `favorite`, `detailRoom` → `room_device`, đích `"{device.entry}"`); `entry` cho biết node nào.
- `"param": "device"` → mỗi thiết bị thuộc root_type này thành một node riêng, vd `KEY_SENSOR_FISRT_SCREEN@thswifi[Cảm biến nhiệt độ]`.
- `"@back"` → bung thành một cạnh Back về mỗi màn có cạnh đi vào node này.
- `anchors` rỗng → node coi là **chưa khám**: `plan()` bỏ qua mọi cạnh vào/ra nó (báo trong `unexplored`),
  nên DISCOVERY không bao giờ hold vào thiết bị khi chưa biết cách nhận ra màn đích.
- `status: "stub"` → `"verified"` sau khi màn được khám, điền anchors và duyệt.
- Các loại cùng nhóm (vd 3 loại switch) có thể dùng `"extends": "switch"` để chung khung — để sau.

## File dự kiến

```
module/parse_data/
├── README.md        # file này
├── __init__.py
├── source.py        # latest_response, check_fresh
├── house.py         # Device, Room, House, parse_house, save/load, diff_house
└── rules.py         # hold_allowed, entry_route, ensure_stub
```
