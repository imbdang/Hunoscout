# Benchmark toàn cục — 2026-11-03 (máy 2fc3878f, Hunonic 4.0.19)

Kịch bản `global_bench.py`: route khắp map (Home, phòng, chi tiết 4 thiết bị, mọi màn feature) + chạy đủ hàm
tương tác (khoá, nhấn nhả, hẹn giờ nhanh, đầu vào AC/DC, hẹn giờ thêm/sửa/xoá, tuần hoàn thêm/sửa/xoá, chia sẻ,
lịch sử, thông tin chung). Ghi thay đổi xong đều trả lại. Số liệu thô: `bench-2026-11-03.json`,
in lại bảng: `.venv/bin/python conversation/bench_report.py conversation/bench-2026-11-03.json`.

Trạng thái code lúc đo: Back mù (BLIND_BACK), bánh xe bấm-điền (Ui.set_wheel), kéo nhích 30 px (u2.drag),
về đầu trang khi chưa biết độ cuộn, tap mù TẮT.

## Tổng

- **138.9 s** · 38 bước kịch bản · 45 bước route · 437 RPC uiautomator2.
- 2 lỗi (chia sẻ: sửa quyền ×2) — không phải lỗi tool: danh sách chia sẻ đã rỗng (imbdang@gmail.com bị gỡ trước khi chạy).

## Thời gian đi vào đâu

| # | Nghẽn | Tổng | Chi tiết |
|---|---|---|---|
| 1 | RPC uiautomator2 | **121.9 s (88 %)** | objInfo 196 × 257 ms = 50.5 s · click 85 × 290 ms = 24.7 s · waitForExists 52 × 456 ms = 23.7 s · dump 43 × 227 ms = 9.8 s · setText 6 × 647 ms · pressKey 16 × 205 ms · injectInputEvent 20 × 109 ms |
| 2 | Chờ màn đích (hiệu ứng trượt của app) | 20.9 s / 45 bước (TB 0.46 s) | nằm trong (1); app dùng @react-navigation/stack (JS) → không theo 3 thang animation hệ thống |
| 3 | Ngủ cứng | 19.6 s (14 %) | adbutils đóng kết nối 470 × 10 ms = 4.7 s · QUICK_DELAY sau mỗi bước route 39 × 0.1 = 3.9 s · pick 0.3 s × 5 · chip thứ 0.25 s × 5 · lưu form 0.5 s |
| 4 | Hold vào ô thiết bị | 4 × 1.8 s | hold 0.95 + chờ màn ~0.5 + kiểm tên 0.3; app chỉ nhận long press ≥ 0.5 s |

### Route theo loại bước

| Loại | Số bước | Tổng | TB | Max |
|---|---|---|---|---|
| tap (toạ độ đã học) | 17 | 14.4 s | 849 ms | 989 ms |
| back (có xác minh) | 10 | 7.7 s | 769 ms | 833 ms |
| hold (toạ độ đã học) | 4 | 7.3 s | 1814 ms | 1832 ms |
| tap trong trang cuộn (cache) | 5 | 6.0 s | 1197 ms | 2094 ms |
| tap phải cuộn 1 lần | 2 | 4.7 s | 2372 ms | 2447 ms |
| back mù | 6 | 1.8 s | 307 ms | 347 ms |

Pha (cộng mọi bước): chờ màn 20.85 s · tap 5.67 s · yên 4.82 s · hold 4.79 s · tìm 3.40 s · back 3.27 s · nghỉ 0.60 s.

## Bước kịch bản chậm nhất

| Bước | Tổng | Ghi chú |
|---|---|---|
| hẹn giờ: thêm 05:55 tắt T2,T6 | 18.05 s | find/chờ 4.9 s · 2 bánh xe 3.4 s · 9 tap 2.2 s · cuộn tới chip · ngủ chip 1.25 s |
| hẹn giờ: sửa 05:55 → 05:57 | 6.89 s | |
| tuần hoàn: thêm 00:20/00:10 | 6.43 s | |
| tuần hoàn: sửa tắt 00:15 | 6.07 s | |
| hẹn giờ nhanh: đặt 3 phút tắt | 6.00 s | chọn số + đọc màu nút |
| tuần hoàn: xoá | 5.16 s | |
| hẹn giờ: xoá | 4.89 s | |
| route → chi tiết Chống giật 4 / Homekit | 4.59 / 4.35 s | 4 bước, có hold 1.8 s |
| nhấn nhả: đặt / trả | 4.30 / 4.29 s | 2 hộp thoại chọn số |
| route → home (lần đầu) | 4.10 s | |
| đầu vào: đọc | 3.84 s | về đầu trang + cuộn tới cuối |
| route: home → chi tiết thiết bị | 3.55–3.64 s | |
| khoá: đặt | 2.8–2.9 s | |
| đầu vào AC: bật/tắt | 1.4–1.6 s | |
| đọc (khoá / nhấn nhả / hẹn giờ nhanh) | 0.2–0.3 s | đang ở màn chi tiết, đọc chữ phụ |

Bước route chậm nhất: chi tiết → Thông tin chung phải cuộn 1 lần 2.3–2.4 s (tìm 1.2 s); chi tiết → Hẹn giờ khi
trang đang ở cuối 2.1 s (về đầu trang 1.0 s); detailRoom → chi tiết (hold) 1.8 s.

## Đo riêng đường RPC (10 lần mỗi loại, màn Chia sẻ)

| Lệnh | Hiện tại (u2 3.x: kết nối adb mới mỗi lệnh) | Giữ kết nối HTTP (adb forward + requests.Session) |
|---|---|---|
| deviceInfo (chỉ đường truyền) | 121 ms | 66 ms |
| objInfo (= locate) | 190 ms | 141 ms |
| click | 243 ms | 188 ms |
| injectInputEvent down+up (tap 2 RPC) | 216 ms | (chưa đo) |

Configurator uiautomator: waitForIdleTimeout 0, waitForSelectorTimeout 0 sẵn; đặt actionAcknowledgmentTimeout 0
không đổi gì. Phần còn lại là việc trên máy: đọc cây ~120 ms, click ~180 ms.

## Đề xuất (chưa làm), xếp theo lợi

1. Giữ kết nối HTTP tới server u2 → −50 ms/RPC ≈ −22 s / 139 s (~16 %), mọi thao tác.
2. Tap = injectInputEvent down+up thay click → ước −7–11 s (85 tap); cần thử app nhận ổn định.
3. Bớt objInfo thừa (`find` = locate rồi wait: không có phần tử là tới 3 RPC) → −10–20 % objInfo.
4. Gỡ ngủ cứng trong form (pick 0.3, _save 0.5, chip 0.25) → ~−5 s. Giữ QUICK_DELAY 0.1 (chặn tap rơi màn cũ).
5. Tắt hiệu ứng chuyển màn (cần root/Frida hoặc cờ từ team app) → −0.3–0.5 s mỗi bước (~−15–20 s), mở được tap mù.

Ước: làm 1–4 → ~100 s; thêm 5 → ~80 s.
