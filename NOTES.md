# Ghi chú nghiên cứu

## 2026-11-03 — i18n 4.0.19, trạng thái máy local

### Bảng i18n (dùng cho `config.I18N` / `Lexicon`)
- Decompile droidsaw 4.0.20 (`~/ReverseProject/HunonicApp/goal/hermes_src/hbc/f008820_.js` vi, `f008821_.js` en)
  **hỏng** ở object literal lớn: mất tên key (`equipmentUsed` → `key76`, `renameDevice` → `_141`),
  key/value lệch buffer (vd `LIGHT: "center"`). Không dùng được. Key thật không đổi — code vẫn gọi
  `translate("equipmentUsed")`.
- Đã trích lại từ bundle **4.0.19** kéo từ máy `2fc3878f` (HBC v96), đọc thẳng object key/value buffer
  + `PutNewOwnById` bằng parser của `hermes-dec`, không qua decompiler:
  function 8807 = vi (4331 key), 8808 = en (4120), 8809 = lo, 8810 = ja.
- File: `~/ReverseProject/HunonicApp/4.0.19/i18n/`
  - `vi.js`, `en.js`, `lo.js` — dạng `"key": "value",` (Lexicon đọc được)
  - `vi.json`, `en.json` — dạng cây (giữ object lồng)
  - `i18n_dump.py` — script trích (chạy bằng venv có `hermes-dec`), `SOURCE.txt` — sha256 bundle, versionCode
- Đã kiểm: mọi i18n key trong `data/huno_pattern/` đều resolve ra chữ vi + en qua `Lexicon`.
- `config.I18N` vẫn trỏ `~/Reverse/HunonicApp/4.0.19/...` (không có trên máy local) — chưa đổi.

### Máy local
- `.venv` đã tạo, cài `uiautomator2` 3.7.1, kết nối được `2fc3878f`.
- Chưa có `data/2fc3878f/` (profile, cache toạ độ, title đã học).
- Chưa có `~/Reverse/HunonicApp/mitm` (hook capture + exports) → chưa chạy được scout.
- rea MCP (`~/ReverseProject/rea`) đã cài, nhưng không giải mã Hermes bytecode.
- `0123456789ABCDEF` trên adb là board RK3568 chạy Linux, không phải Android.

### App trên `2fc3878f` (Hunonic 4.0.19, 1220x2712, density 480)
- `home` và `home → room` (tap glyph view-grid) khớp `core.json`: anchor `equipmentUsed`, `roomManager`,
  đủ 5 glyph tab bar, desc thẻ phòng dạng `"<tên phòng>, Thiết bị (n)"` (match `prefix`).
- Nhà hiện tại: 3 phòng — Chưa xếp phòng (6), Nhà tắm (0), aa (0); 6 thiết bị — Thiết bị trung tâm Homekit,
  Công tắc 1/2/3, Module Input 5, Công tắc ngữ cảnh. **Không còn "Ổ cắm"** → pattern `sswitch2v` có thể
  không áp vào thiết bị nào; root_type thật cần response hook để xác nhận.
- Home đang có banner "Lời mời tham gia nhóm trung tâm RF" — chưa có node nếu nó bật popup.
- `UI_SCREEN_INDEX.md` của repo reverse có ID không tồn tại (vd `f023820_DetailRoomScreen.js`).

## 2026-11-03 — chạy DISCOVERY trên máy local + map Module Input (`swinputv2`)

### Chạy được scout trên máy local
- Danh sách nhà/thiết bị lấy tay từ hook: `adb logcat -G 16M`, `logcat -c`, đọc liên tục tag `HUNONIC_REST_QA`
  từ TRƯỚC khi mở lại app (đọc `-d` sau đó thì mất dòng BODY). Body = các dòng `BODY <id> i/n <base64>`, ghép
  response của `.../v3/device/listDeviceOfHomeSelectv2`. Ghi vào `~/Reverse/HunonicApp/mitm/exports/` → chạy `--no-fresh`.
- `~/Reverse/HunonicApp/4.0.19/js/app/.../872_user.js`, `873_user.js` = symlink tới bảng i18n đã trích.
- Cắm 2 thiết bị adb → phải đặt `ANDROID_SERIAL=2fc3878f`.
- DISCOVERY core: 10 cạnh + title trong 18.5 s.

### Bảng i18n: sửa key lồng
- Bảng có key trùng tên ở object lồng (vd `pressMode` gốc = "Chế độ nhấn nhả", `gate.pressMode` = "Cài thời gian nhả nút").
  Bản trích mới ghi key lồng theo đường dẫn chấm (`neo.contextButtonLink`, `ATM.actionNone`) + tên ngắn làm fallback
  ghi TRƯỚC để key gốc thắng (`assistant` chỉ có ở `guideAutoSwitchHouse.assistant` vẫn tra được).

### Module Input 5 = `swinputv2` (type switch)
- Pattern `data/huno_pattern/root_type/swinputv2.json`: `infoDevice` (giống sswitch2v + 4 dòng riêng) và `contextLink`
  (`DeleteLinkNeoScreen`). Đầu vào: AC = công tắc gửi lệnh (action/danger); DC (Xanh)/(Đỏ) = sheet `selectAction` (popup).
  Chữ ghép `inputText + " AC"` / `" DC (" + colorGreen|colorRed + ")"` → target dùng `text` tiếng Việt.
- Header phải là thùng rác = xoá thiết bị.
- Đã đi thật: detailRoom → hold → infoDevice → contextLink → back → infoDevice → back → detailRoom → … → home.

### Dòng chỉ hiện khi đã liên kết (neo R6, ST02)
- App: `useNeoLogic(device).listLinkedNeo` / `useSt02Logic(device).listLinkedSt02`. REST: `data_extra.neoLinks`
  (khoá = root_id công tắc ngữ cảnh) / `data_extra.listSt02Linked`.
- `Device.neo_links`, `Device.st02_links` (đếm từ data_extra). Control gắn `"when": "neo_links != 0"` → chưa liên kết thì
  không sinh cạnh (không lạc).
- `pattern._layout`: control có `when` đang hiện → vào `sig` mọi cạnh của màn đó. Dòng hiện/ẩn làm dịch toạ độ các dòng
  dưới → trạng thái đổi thì toạ độ cũ của cả màn mất hiệu lực, tự học lại. Màn không có control `when` → sig như cũ.
- Giả định `neoLinks` khác rỗng ⇔ dòng hiện: mới kiểm ở trạng thái đã liên kết (1 liên kết); chưa kiểm khi bỏ liên kết.

### Lỗi đã thấy, chưa sửa
- Màn có `scroll`: `Navigator._find()` tìm mọi target bằng `reach()` trong vùng cuộn → nút ‹ header (ngoài vùng cuộn)
  không bao giờ "inside" → kéo hết trang rồi Lost (~15 s). sswitch2v cũng dính. swinputv2 tạm dùng Back hệ thống.

## 2026-11-03 — trang web xem map + route bằng click (`module/web/`)
- Chạy: `ANDROID_SERIAL=2fc3878f .venv/bin/python -m module.web --no-fresh [--port 8765]` → http://127.0.0.1:8765
- Server (`server.py`, stdlib `http.server`) giữ một Scout ACTIVE: `GET /api/graph`, `GET /api/path?dst=` (Dijkstra +
  ước tính = tổng cost_ms), `POST /api/goto` (NDJSON: plan → step… → done|error), `POST /api/where` (nhận diện lại).
  Mỗi lần một goto (lock). Hook `Navigator.on_move(edge, how, ms)` gọi sau mỗi bước.
- Trang (`index.html`, Cytoscape.js 3.30.2 từ cdnjs): hover node = đường dự kiến + ước tính; click = route thật, panel
  phải hiện từng bước (ms thực tế vs ước tính, cache/hỏi máy/học cạnh/back), lịch sử lần chạy. Vị trí node lưu localStorage.
- Đo lần đầu: home → contextLink 4 bước 5.5 s (ước tính 7.9 s); contextLink → detailRoom 2 bước back 1.66 s.

### Sửa: vào Module Input bị kéo xuống liên tục (2026-11-03)
- Dòng "Liên kết công tắc ngữ cảnh" hiện SAU khi thiết bị trả lời lệnh `getCmdGetListLinkNeor6` (gửi lúc mở màn,
  useNeoLogic → loadData). Thiết bị offline → không bao giờ hiện, dù REST `data_extra.neoLinks` vẫn có → `when` chỉ là gợi ý.
- Trước: không thấy dòng → `reach()` kéo hết trang → Lost → goto thử lại 3 lần (hold vào lại, kéo tiếp) ≈ 30 s.
- Giờ: cạnh từ control có `when` là `Edge.optional`. `Navigator._present()` chờ nút hiện tại chỗ (WAIT_OPTIONAL 3 s,
  không cuộn; chỉ cho cuộn khi vị trí đã học nằm dưới khung nhìn). Không có → `Absent` (không thử lại, không ghi cache).
  Đo khi thiết bị offline: báo Absent sau ~3.4 s, trang vẫn ở đầu. Trường hợp online (dòng hiện muộn) chưa đo lại.
- `/api/where` lỗi khi POST không body (ưu tiên toán tử `int(...) or b"{}"`) — đã sửa.

### Sửa: route vào Homekit lại vào Module Input (2026-11-03)
- Nguyên nhân 1: cạnh hold ô thiết bị dùng toạ độ cache (996,892) học lúc trước; thứ tự ô trong detailRoom đổi theo
  trạng thái thiết bị → bấm nhầm ô. Giờ target `desc` (tên thiết bị/phòng) luôn hỏi máy (~0.13 s), không dùng xy cache.
- Nguyên nhân 2: xác minh nhanh chỉ chờ title đúng dải y — mọi infoDevice cùng title "Chi tiết thiết bị". Giờ sau
  wait_band kiểm thêm `check_text` (tên thiết bị) có trên màn; không có → Lost → nhận diện lại, đi lại.
- Bỏ cạnh Home → thiết bị (mục "Thiết bị hay dùng") và placeholder `favorite` khỏi core.json: vào thiết bị chỉ qua
  room → detailRoom.
- Sau sửa: route Homekit 2 lần đều đúng màn.
- Nhà đã đổi so với response 08:25: Module Input 5 đổi tên thành "Công tắc", thêm "Cảm biến cầu thang", Homekit
  "Thiết bị con: 0" → route "Module Input 5" báo không tới được cho tới khi lấy lại danh sách thiết bị.

## 2026-11-03 — map feature của Module Input (`swinputv2`, thiết bị "Công tắc ")
- Nhà đổi (capture lại 09:35): Module Input 5 bị xoá, thêm lại tên "Công tắc " (thừa dấu cách cuối, id 4076072),
  thêm "Chống giật 4" (GACHshock). Script lấy danh sách: scratchpad `capture.py` (logcat → exports). Cache cũ tự prune.
- Feature (data/huno_pattern/feature/): share {list, add}, timer {list, add}, cycle {list, add}, history {list},
  general_info {info}. Tham chiếu Wallpad docs/device/feature/<feature>/swinputv2.md. Màn add chỉ mở rồi Back,
  không lưu: nút Lưu lại / Chia sẻ là danger. "Lặp tuần hoàn" là màn (KEY_NAME_TIMER_LOOP_LIST_SCREEN), không phải popup.
- Engine:
  - anchor spec `{"key": [...], "suffix": " {device.name}"}` cho title ghép (Hẹn giờ/Lịch sử/Thêm hẹn giờ + tên);
    `"match": "prefix"` cho chữ ghép số ("Danh sách người được chia sẻ (n)"). `anchors` nhận spec dict và được điền ctx.
  - so khớp bỏ khoảng trắng hai đầu (tên "Công tắc ", desc "AC, DC, Công tắc , Đang tắt").
  - u2: phần tử biến mất giữa tìm/đọc (StaleObjectException) → coi như chưa thấy, hỏi lại (trước: văng lỗi RPC).
  - `@back` chỉ tính cạnh đi tới (trước: add→list (back) làm list có back sang add).
  - infoDevice anchors thêm statusPower/generalInformation: Back từ màn con giữ vị trí cuộn, đầu trang không còn.
- Đo (cache): home→timer/add 5 bước 7.8 s; timer/add→general_info 5.1 s; general_info→cycle/add 3.8 s;
  cycle/add→home 5 bước 5.9 s. Mỗi bước ~0.9–2.5 s (hold ~2.5 s, cuộn tới general_info ~2.9 s).
- Chưa khám: dòng hẹn giờ/tuần hoàn/người chia sẻ đã có (danh sách đang rỗng), các dòng trong general_info
  (Chủ sở hữu, Wifi, Bảo hành, Phiên bản phần cứng — có thể OTA), nút góc phải general_info, qr_link (mở camera).

## 2026-11-03 — web: nút "Discovery lại" + "Làm mới"
- "Discovery lại" (modal xác nhận) → `POST /api/discovery` (NDJSON log → done|error): `Scout.stop()` rồi
  `Scout.start(fresh=True)` = mở lại app lấy danh sách qua hook, dựng lại map, prune toạ độ cũ, học core + title còn thiếu.
  Panel hiện thời gian, số thiết bị, cạnh/title mới, toạ độ đã xoá, lỗi, màn mới/bỏ, log 📍.
- "Làm mới" → `POST /api/refresh`: `Scout.load(fresh=False)` dựng lại map từ pattern + exports đã lưu, không chạm màn hình,
  giữ pointer. Web vẽ lại giữ vị trí node cũ; node mới (kể cả chưa có đường đi) đặt cạnh láng giềng, viền cyan nét đứt.
- `Scout.start` tách thành `load()` (IDLE, gọi lại được) + phần DISCOVERY.
- Lấy danh sách khi không có direct-capture.py: `parse_data.LogcatCapture` (logcat HUNONIC_REST_QA → exports/,
  file log tạm có body REST bị xoá khi stop). Đo: 4.1 s; discovery không thiếu cạnh: 4.9 s tổng.
- Discovery KHÔNG xoá cache toạ độ còn hợp lệ (chỉ prune node/cạnh không còn). popup.switchHouse luôn báo 1 lỗi
  "học title: không có đường" (popup không có cạnh vào) — có từ trước.
- Sửa: discovery luôn báo "lỗi 1" (popup.switchHouse: học title: không có đường). `Scout.unlearned()` giờ bỏ màn
  không có cạnh vào (popup tự bật) như `plan()` → khởi động / discovery báo 0 lỗi. Thiết bị mới thêm để test:
  "Aptomat" (atmwifiv2) — có node leaf infoDevice, cạnh hold từ detailRoom học khi route lần đầu.

## 2026-11-03 — lối tắt thiết bị (Thêm lối tắt) và deep link
- MIUI chặn lặng lẽ lối tắt màn hình chính nếu app chưa có quyền "Lối tắt trên màn hình chính" (appop MIUI 10017).
  Đã bật cho com.iot.hunonic: `adb shell appops set com.iot.hunonic 10017 allow`. Icon mới MIUI đặt ở trang cuối launcher.
- Lối tắt = ShortcutInfo id `#<device.id>` → `com.hunonic.WidgetHuoninc.WidgetOpenActivity` (extra KEY_INTENT_SEND_DATA_ID,
  KEY_INTENT_SEND_DATA_TYPE_DEVICE) → activity dựng `hunonic://app/infoDevice/<id>` rồi mở app (extra loại thiết bị bị bỏ qua).
- linking config (f005055): prefixes hunonic://app…; `infoDevice/:id` → màn `splash` (params device.id / deepLink / navKey).
- Đo: deep link / icon → infoDevice của thiết bị: Công tắc 2.4 s, Aptomat 3.2 s (từ launcher). Back sau deep link về Home.
- atmwifiv2: hold và deep link đều vào infoDevice (menu SettingAtmInfoMenuView). Màn đo điện
  (KEY_NAME_DETAIL_ELECTRIC_METER_SCREEN) chỉ mở khi tap ô + confirm_turn bật, hoặc bấm thông báo (atmwifi v1).
  Aptomat confirm_turn=0 → tap = bật/tắt thật. Loại khác (quạt, cửa, cảm biến…) hold có thể khác deep link — chưa thử.
- Đo deep link → infoDevice "Công tắc " (animation 1x): từ Home app ~2.5 s (2.3–2.7), từ màn sâu 3.1–4.4 s; tap từ Home 5.5 s.
  ~1–2 s đầu app nằm ở màn splash. Từ infoDevice của THIẾT BỊ KHÁC: màn trắng, không vào (3/3 lần) — lỗi app.
- Tắt 3 thông số animation (0): không nhanh hơn (deep link 3.6 s, tap 6.4 s; 1 lần có lúc deep link kẹt) → đã trả về 1x.
  Máy lag do RAM gần đầy (free 168 MB, swap 2.7 GB), CPU rảnh.

## RULE — xác minh tới màn (2026-11-03, theo yêu cầu)
**Không dump full màn để xác minh.** Scout luôn biết màn đích (route/node) của bước đang đi → chỉ hỏi máy đúng
tổ hợp chữ của màn đó (uiautomator2 selector, ~0.13 s/lần hỏi), thứ tự ưu tiên trong `Navigator._verify`:
1. Title đã học vị trí + không trùng màn nguồn → chữ title ở đúng dải y (vị trí + chữ); title chung (vd
   "Chi tiết thiết bị") → kiểm thêm tên riêng (check) — bỏ nếu title chính là tên đó.
2. Title không cố định vị trí (Home) → chữ anchor ở bất kỳ đâu.
3. Title trùng màn nguồn / chưa học → **chữ riêng của màn đích** (`unique_selector`: anchors đích trừ chữ màn nguồn;
   nhóm [a, b] gộp 1 lần hỏi; "match": "prefix" cho chữ ghép số). Vd share list ↔ add.
4. Không có chữ riêng → **đủ bộ anchors** (`anchor_selectors`: mỗi nhóm 1 lần hỏi + tên riêng).
Chữ ở phần cố định nên kèm vị trí (band) cho chắc duy nhất; chữ trong vùng cuộn chỉ dùng chữ (vị trí đổi theo cuộn).
Dump chỉ còn khi KHÔNG biết đang ở đâu (`where()` lúc lạc), học title lần đầu, discovery đọc list ô thiết bị.
Đo: Back share/add→share/list 1.35 s (dump) → 0.56 s; general_info→infoDevice (trang cuộn cuối) ~1.5 s → 0.58 s.

## 2026-11-03 — tốc độ route (đã chốt)
- Tap thẳng toạ độ đã học: tab, nút, thẻ phòng, ô thiết bị, dòng trong vùng cuộn (content_y − độ cuộn + dy).
- Thấy màn đích → nghỉ 0.1 s rồi đi tiếp (`QUICK`), không chờ màn trượt xong. Chế độ mù (`BLIND`) đã thử và TẮT:
  app chuyển màn ~0.4–0.6 s, tap sau 0.1 s rơi vào màn cũ → kẹt ~15 s/lần.
- Hold 0.8 s (0.55 s tới màn như nhau ~1.47 s; app chuyển từ mốc long press 500 ms) — giữ 0.8 s cho khỏi thành tap.
- Toạ độ đã học mà thao tác thất bại (không mở màn / mở nhầm) → `Resolved.forget`, lần thử lại tìm theo tên.
- Discovery (fresh) quét lại ô thiết bị từng phòng: 1 dump/phòng → ghi đè toạ độ mọi ô (`Navigator.scan_tiles`).
- Mỗi bước còn ≈ gửi chạm 0.2–0.25 s + app chuyển màn 0.4–0.7 s + 0.1 s.

## 2026-11-03 — hàm tương tác feature (`module/actions/`, thử trên "Công tắc " swinputv2)
`ANDROID_SERIAL=2fc3878f .venv/bin/python -m module.actions <lệnh> --device "Công tắc " …` (xem docstring `__main__.py`):
lock-get/lock-set, timer-list/add/edit/delete (giờ, mặt trời mọc/lặn; một lần/tuần/tháng; bật/tắt/khoá trẻ em),
share (--phone/--email, --perms), share-edit WHO --perms, unshare WHO.
- Quyền chia sẻ ghi theo loại thiết bị ở `root_type/<rt>.json` → `"share": {"perms", "default"}` (nguồn Wallpad
  docs/device/feature/share/<rt>.md). swinputv2 / sswitch2v: 7 quyền control, timer, collection, basic, advanced,
  history, notify_offline; mặc định 6 đầu. `share.py` chỉ tìm đúng các dòng đó trong 1 dump + 1 ảnh chụp (đọc quyền ~0.5 s).
  Loại thiết bị mới: thêm khối "share" vào file root_type (thiếu thì dùng cả 7).
- Danh sách người được chia sẻ: sđt hiện "0396674953 - Tùy chỉnh", email hiện "imbdang@gmail.com\nTùy chỉnh"
  (`shared_users` trả cả hai về dạng "<ai> - <quyền>"). Icon ✏️ (x = w−305) / 🗑 (x = w−174) không có trong cây UI.
- Đã thử: share sđt + email, share-edit (7 quyền → control,history, đọc lại khớp), unshare.
- Chế độ nhấn nhả / Hẹn giờ nhanh (`press.py`): hộp thoại, ô số bấm → danh sách chọn native (Button chữ số trong
  RecyclerView). `Ui.pick_number`: xa thì vuốt nhanh, gần thì kéo chậm đúng số dòng, chỉ bấm khi dòng đã đứng yên
  (bấm lúc còn trôi = chỉ dừng cuộn). Hộp thoại không hiện giá trị đang đặt → đọc từ chữ phụ của dòng
  (nhấn nhả: khớp theo mẫu i18n clickModeLAN*, vì tên thiết bị có thể có số). Đã thử: nhấn nhả 01:25, 07:45, 00:00;
  hẹn giờ nhanh 45 phút tắt, 200 phút bật (ra 18:09), xoá.
- Lặp tuần hoàn (`cycle.py`): cycle-add/edit/delete/list. Bánh xe 2 hàng → sắp theo (y, x). Bánh xe sát header →
  mỗi lần kéo tối đa số nấc còn chỗ trên màn (không thì toạ độ âm). Đã thử: mãi mãi 00:10/00:05; giới hạn
  20:00–22:30 T2/T4/T6 (ảnh khớp); tắt lặp tuần + đổi ngày sang 20/12/2026; xoá. Thêm giới hạn nhiều nấc ~45 s.
- Lịch sử (`history.py`): đọc các dòng đang thấy → [{"event", "at"}], ~4 s kể cả khởi động.
- RemoteDisconnected cách 1 lần chạy: u2 tắt server khi tiến trình thoát (atexit, không chờ) → lần chạy sau dùng
  server đang chết. `interact/u2.py` vá `jsonrpc_call`: ConnectionError → bật lại server rồi hỏi lại (4/4 lần qua).

## 2026-11-03 — cuộn: dừng đúng cuối trang + kéo nhanh; web chuột phải chạy hàm
- `interact/u2.drag`: down → nhích 30 px (NUDGE, qua ngưỡng chạm) → nhảy thẳng tới đích → giữ 0.05 s → up.
  Đo: 0.45–0.55 s/lần (trước 0.6–0.7 s), cuộn đúng |kéo| − 30 mọi lần (trước 3 bước mất trọn bước đầu: 400 → 266).
  swipe / swipe_points đều văng. `scroll.SLOP` = 30 (trước 50, sai).
- `scroll.reach`: mốc đo cuộn lấy lại trước mỗi lần kéo (ref nếu kéo xong còn trên màn, không thì `u2.lowest` = dòng
  bấm được thấp nhất đang thấy). Trước: mốc renameDevice trôi khỏi màn ngay lần đầu → không biết chạm cuối → kéo đủ 8
  lần (tìm phần tử không có: 7.8 s, ghi cuộn 9480 px trên trang chỉ cuộn được 853 px). Giờ: 2 lần, 3.5 s, đúng 853.
  Kéo theo vị trí đã học (content_y): đo bằng chính phần tử đích, không cần mốc.
- content_y học bằng reach cũ có thể sai (general_info Công tắc: 3656, thật ~3324) → đã xoá cho học lại.
- `Ui.drag` (bánh xe, danh sách chọn số) dùng u2.drag, giữ 0.3 s: ~0.7 s/lần (trước ~1.6 s); bánh xe ±5/±7/±10 nấc đúng.
  Tuần hoàn giới hạn: 45 s → 35 s.
- Form "Tạo tuần hoàn" KHÔNG chắc mở ở 00:01: giữ vị trí bánh xe lần mở trước (kéo rồi bỏ không lưu → lần sau
  lệch). `add_cycle` lưu xong đọc dòng mới, lệch thì sửa lại qua form sửa (mở đúng giá trị của dòng).
- Aptomat (`atmwifiv2`, 1 màn): `root_type/atmwifiv2.json` tối thiểu (back + general_info). Thông tin chung dưới mép
  màn: lần đầu cuộn 2 lần (tìm 4.0 s), lần sau tap theo vị trí đã học ~1.0 s. Mốc nhận màn phải có cả dòng giữa/cuối
  trang (Back giữ độ cuộn) — chỉ mốc đầu trang thì Back báo lạc, đi lại từ phòng ~18 s.
- Web: chuột phải vào node (đồ thị hoặc danh sách bên trái) → menu hàm theo `module/actions/catalog.py` → form tham
  số → `POST /api/action` (NDJSON: bước route, log, kết quả). Màn chi tiết thiết bị: mọi hàm của thiết bị; màn feature:
  hàm của feature đó; loại thiết bị thiếu dòng (vd không có press_mode) thì không hiện.
- Lỗi lock-set chập chờn (nhất là "Không khoá"): sheet "Khoá công tắc" có nút ▼ () đè giữa mép dưới danh sách,
  cách tâm dòng cuối ~15 px; `Ui.pick` bấm tâm dòng → lúc trúng dòng, lúc trúng ▼ (sheet đứng im, không chọn gì, hàm báo
  "sheet không đóng"). Sửa: bấm phần chữ bên trái dòng. Thử qua web API: none/device/none/app/none/both đều được, ~2.8 s.
- Bánh xe giờ/phút (hẹn giờ, tuần hoàn): BẤM số đang chọn ở giữa bánh xe → hộp thoại native "Nhập giá trị (0 - 59)"
  (ô EditText có sẵn giá trị hiện tại, Huỷ / OK) → `Ui.set_wheel`: setText 1 RPC + click(selector) OK + wait_gone.
  Không cần cuộn, không cần biết bánh xe đang ở đâu. ~1.5–2.3 s/bánh xe (RPC trên máy này 0.3–0.8 s).
  Hộp thoại mở bằng JS: sau lần đặt trước JS còn bận → có lúc mở trễ > 1 s; bấm lại sớm = hộp thoại THỪA bật lên
  sau khi xong (đã gặp, chặn route sau đó). Nên bấm 1 lần chờ tới 4 s; còn hộp thoại thừa thì Huỷ trước. 16/16 lượt ok.
  Tuần hoàn giới hạn: 45 s → 27 s; danh sách tuần hoàn rỗng chờ chữ AddAlarm (trước mất 3 s); chip thứ 1 dump.
- Bánh xe trùng giá trị đang hiện thì KHÔNG đặt lại; giá trị đang hiện tool tự biết (thêm hẹn giờ: giờ máy +1;
  sửa: giá trị của dòng; thêm tuần hoàn: 00:01 / giờ máy +1,+2). Thêm tuần hoàn mặc định: 0 bánh xe, 4.1 s; đổi 1 ô: 1 bánh xe.

## 2026-11-03 — đầu vào AC/DC, Thông tin chung; độ cuộn khi hàm tự cuộn trang
- `inputs.py`: inputs-get / input-ac-set on|off / input-dc-set green|red on|off|none (Module Input). Dòng cuối trang →
  `Ui.reach` = scroll.reach của navigator + cộng độ cuộn vào pointer (route sau tap theo content_y − độ cuộn).
  Đo: đọc cả 3 ~1.5 s (đang ở màn chi tiết), đặt AC ~1.4 s, đặt DC ~2.7 s. Đã thử bật/tắt/none cả 2 màu rồi trả về.
- `info.py`: general-info → {"fields": {nhãn: giá trị}, "firmware": {"version", "status"}} (vd 260331 / Mới nhất).
  Chỉ đọc; bấm "Phiên bản phần cứng" là luồng cập nhật firmware — chưa làm. Chạy cả Aptomat.
- Lỗi độ cuộn đã sửa: tiến trình mới / Back về trang đang cuộn → pointer chưa biết, code coi là 0 → tap nhầm dòng,
  học content_y sai (general_info Công tắc lại bị sai một lần). `reach` chỉ cuộn xuống → dòng phía trên không tìm lại.
  Giờ `Navigator._find`: độ cuộn chưa biết hoặc nút nằm phía trên khung → `to_top` trước (đã có sẵn, trước không ai gọi;
  mốc đã ở đầu trang thì chỉ 1 lần hỏi máy); cuộn xuống không thấy mà trang đang giữa chừng → về đầu, tìm lại.
  reach không thấy vẫn cộng độ cuộn đã kéo. Đo: cuối trang → Hẹn giờ/Chia sẻ ~1.9 s (về đầu + cache), Lịch sử 1.0 s.

## 2026-11-03 — Back mù + vì sao không tắt được hiệu ứng chuyển màn
- `Navigator.BLIND_BACK`: Back mà bước sau cũng là Back → bấm phím, nghỉ 0.1 s, đi tiếp; chỉ xác minh màn cuối chuỗi.
  Phím Back Android xếp hàng gửi cho cửa sổ đang mở → không có lỗi "tap rơi vào màn cũ" như BLIND tap (vẫn tắt).
  Back mù 0.21–0.33 s/bước (xác minh 0.6–0.7 s). Back không kiểm tên thiết bị (màn quay về đã biết) → −0.2 s.
  Lập đường: Back đã học tính 300 ms (`_cost`) để ưu tiên nối chuỗi Back; Back chưa học giữ chi phí cũ.
  timer/add → home: 3.35 s → 2.53–2.62 s. detailRoom → room vẫn tap ‹ (Back hệ thống ở detailRoom sai — xem core.json).
- Hiệu ứng: app dùng @react-navigation/stack (JS, Animated; bundle có createStackNavigator / forHorizontalIOS;
  cây view chạy là ScreenContainer/ScreenFragment, không ScreenStack) → KHÔNG theo 3 thang animation của Developer
  options (đã thử: tắt vẫn trượt). Máy không root. Muốn tắt: app thêm cờ cho bản test (vd animationEnabled: false khi
  AccessibilityInfo.isReduceMotionEnabled / cờ debug) hoặc đóng gói lại APK (sửa bundle / Frida gadget) — chưa làm.

## 2026-11-03 — benchmark toàn cục
Số liệu + kịch bản + dữ liệu thô: `conversation/2026-11-03-benchmark.md` (138.9 s, 88 % thời gian là RPC uiautomator2).
