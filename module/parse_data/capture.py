"""Lấy danh sách nhà/thiết bị MỚI qua hook REST trong APK (không lưu cứng, mỗi lần chạy lấy lại).

APK 4.0.19 đã vá ghi body REST ra logcat; ~/Reverse/HunonicApp/mitm/scripts/direct-capture.py
đọc logcat (start), ghép thành file và copy response danh sách mới nhất ra exports/ (export).
Ở đây chỉ gọi script đó: start → (scout mở lại app) → chờ export có response mới hơn lúc start → stop.
"""
from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from .source import DataError


class Capture:
    def __init__(self, script: Path, serial: str):
        self.script, self.serial = script, serial
        self.since: datetime | None = None

    def _run(self, cmd: str) -> subprocess.CompletedProcess:
        return subprocess.run(["python3", str(self.script), cmd, "--serial", self.serial],
                              capture_output=True, text=True, timeout=30)

    def start(self) -> None:
        """Bật collector. Gọi TRƯỚC khi app tải danh sách (logcat có bộ đệm giới hạn)."""
        self.since = datetime.now(timezone.utc)
        p = self._run("start")
        if p.returncode != 0:
            raise DataError(f"không bật được collector của hook: {p.stderr.strip() or p.stdout.strip()}")

    def wait_list(self, timeout: float = 40) -> datetime:
        """Chờ tới khi export có response danh sách ghi nhận SAU lúc start → thời điểm ghi nhận."""
        end = time.monotonic() + timeout
        last = ""
        while time.monotonic() < end:
            p = self._run("export")
            if p.returncode == 0:
                summary = json.loads(p.stdout.split("inventory=")[0])
                observed = datetime.fromisoformat(summary["observed_at"])
                if observed >= self.since:
                    return observed
                last = f"response mới nhất vẫn là lúc {observed:%d/%m %H:%M:%S}"
            else:
                last = (p.stderr or p.stdout).strip()
            time.sleep(1.5)
        raise DataError(f"{timeout:.0f}s không thấy response danh sách mới ({last}). "
                        "App có phải bản hook không? (chữ ký 4e1c36f5)")

    def stop(self) -> None:
        self._run("stop")
