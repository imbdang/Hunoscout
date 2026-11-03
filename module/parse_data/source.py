"""Đọc response danh sách nhà/thiết bị do hook REST ghi ra."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

RESPONSE = "latest-homes-devices-response.json"
INVENTORY = "latest-home-device-inventory.json"


class DataError(RuntimeError):
    """Dữ liệu đầu vào thiếu hoặc sai."""


def latest_response(exports: Path) -> tuple[dict, datetime]:
    """(response, thời điểm ghi nhận). Thời điểm lấy từ inventory, thiếu thì dùng mtime file."""
    path = exports / RESPONSE
    if not path.exists():
        raise DataError(f"chưa có {path} — chạy direct-capture.py start, mở app tải danh sách, rồi export")
    resp = json.loads(path.read_text(encoding="utf-8"))
    if resp.get("status") is not True or not isinstance(resp.get("data"), list):
        raise DataError(f"{path.name}: response không hợp lệ (status={resp.get('status')!r})")

    observed = None
    inv = exports / INVENTORY
    if inv.exists():
        try:
            observed = datetime.fromisoformat(json.loads(inv.read_text(encoding="utf-8"))["observed_at"])
        except (KeyError, ValueError):
            observed = None
    if observed is None:
        observed = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    return resp, observed


def check_fresh(observed_at: datetime, max_age: timedelta) -> str | None:
    """Câu cảnh báo nếu dữ liệu cũ hơn `max_age`, ngược lại None."""
    age = datetime.now(timezone.utc) - observed_at
    if age <= max_age:
        return None
    return (f"dữ liệu thiết bị đã cũ {age.total_seconds() / 3600:.1f} giờ — "
            "mở app, tải lại danh sách rồi chạy direct-capture.py export")
