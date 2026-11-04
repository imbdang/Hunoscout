"""Lấy danh sách nhà/thiết bị MỚI qua hook REST trong APK (không lưu cứng, mỗi lần chạy lấy lại).

APK 4.0.19 đã vá ghi body REST ra logcat; ~/Reverse/HunonicApp/mitm/scripts/direct-capture.py
đọc logcat (start), ghép thành file và copy response danh sách mới nhất ra exports/ (export).
Ở đây chỉ gọi script đó: start → (scout mở lại app) → chờ export có response mới hơn lúc start → stop.
"""
from __future__ import annotations

import base64
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from .source import INVENTORY, RESPONSE, DataError


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


class LogcatCapture:
    """Thay Capture khi máy này không có direct-capture.py: đọc thẳng logcat của APK đã vá.

    Hook ghi tag HUNONIC_REST_QA: "REQUEST|META <id> ... <b64 url>", "BODY <id> i/n <b64 khúc>", "END <id>".
    Bắt đầu đọc TRƯỚC khi mở app (buffer logcat lớn, đọc liên tục — đọc sau dễ mất dòng BODY), ghép body của
    listDeviceOfHomeSelectv2 rồi ghi exports/ giống script export (response + inventory có observed_at).
    """
    TAG = "HUNONIC_REST_QA"
    URL = "listDeviceOfHomeSelectv2"

    def __init__(self, exports: Path, serial: str):
        self.exports, self.serial = exports, serial
        self.log = exports / ".logcat-capture.log"     # có body REST (khoá thiết bị) → xoá khi stop
        self.since: datetime | None = None
        self._proc: subprocess.Popen | None = None
        self._out = None

    def _adb(self, *args: str) -> None:
        subprocess.run(["adb", "-s", self.serial, *args], capture_output=True, timeout=30)

    def start(self) -> None:
        self.exports.mkdir(parents=True, exist_ok=True)
        self._adb("logcat", "-G", "16M")
        self._adb("logcat", "-c")
        self._out = open(self.log, "w", encoding="utf-8")
        self._proc = subprocess.Popen(["adb", "-s", self.serial, "logcat", "-v", "raw", "-s", f"{self.TAG}:I"],
                                      stdout=self._out)
        self.since = datetime.now(timezone.utc)

    def _body(self) -> str | None:
        """Body đầy đủ của response danh sách (đã END, đủ mọi khúc), chưa có → None."""
        urls: dict[str, str] = {}
        parts: dict[str, dict[int, str]] = {}      # id request → {thứ tự khúc: base64}
        total: dict[str, int] = {}                 # id request → số khúc
        for line in self.log.read_text(encoding="utf-8", errors="replace").splitlines():
            p = line.split()
            if len(p) >= 3 and p[0] in ("REQUEST", "META"):
                urls[p[1]] = base64.b64decode(p[-1]).decode()
            elif len(p) == 4 and p[0] == "BODY":
                i, n = map(int, p[2].split("/"))
                parts.setdefault(p[1], {})[i] = p[3]
                total[p[1]] = n
            elif len(p) == 2 and p[0] == "END" and self.URL in urls.get(p[1], ""):
                ch = parts.get(p[1], {})
                if ch and len(ch) == total[p[1]]:
                    return base64.b64decode("".join(ch[i] for i in sorted(ch))).decode()
        return None

    def wait_list(self, timeout: float = 45) -> datetime:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            time.sleep(1)
            if body := self._body():
                resp = json.loads(body)
                if resp.get("status") is not True:
                    raise DataError(f"response {self.URL} status={resp.get('status')!r}")
                for name, obj in ((RESPONSE, resp), (INVENTORY, {"observed_at": self.since.isoformat(timespec="seconds"),
                                                                 "source": "logcat HUNONIC_REST_QA (LogcatCapture)"})):
                    path = self.exports / name
                    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
                    path.chmod(0o600)
                return self.since
        raise DataError(f"{timeout:.0f}s không thấy response {self.URL} đầy đủ trong logcat {self.TAG}. "
                        "App có phải bản hook không?")

    def stop(self) -> None:
        if self._proc:
            self._proc.kill()
            self._proc.wait()
        if self._out:
            self._out.close()
        self.log.unlink(missing_ok=True)


class MitmCapture:
    """App không có hook (bản 4.0.23 ký lại cho mitm): đọc response danh sách trong flows.jsonl của sniff_api.py
    (HunonicMitm) — chỉ các dòng ghi SAU start(), rồi ghi exports/ giống LogcatCapture."""
    PATHS = ("/v3/device/listDeviceOfHomeSelect", "/v3/device/listDeviceOfHomeSelectv2")

    def __init__(self, exports: Path, flows: Path):
        self.exports, self.flows = exports, flows
        self.since: datetime | None = None
        self._pos = 0

    def start(self) -> None:
        self.exports.mkdir(parents=True, exist_ok=True)
        self._pos = self.flows.stat().st_size if self.flows.exists() else 0
        self.since = datetime.now(timezone.utc)

    def _latest(self) -> dict | None:
        if not self.flows.exists():
            return None
        with open(self.flows, "rb") as f:
            f.seek(self._pos)
            lines = f.read().decode("utf-8", "replace").splitlines()
        found = None
        for line in lines:
            try:
                flow = json.loads(line)
            except ValueError:                     # dòng cuối đang ghi dở
                continue
            if flow.get("path") in self.PATHS and isinstance(flow.get("resp_body"), dict):
                found = flow["resp_body"]
        return found

    def wait_list(self, timeout: float = 45) -> datetime:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            time.sleep(1)
            if resp := self._latest():
                if resp.get("status") is not True:
                    raise DataError(f"response danh sách thiết bị status={resp.get('status')!r}")
                for name, obj in ((RESPONSE, resp), (INVENTORY, {"observed_at": self.since.isoformat(timespec="seconds"),
                                                                 "source": f"mitm {self.flows} (MitmCapture)"})):
                    path = self.exports / name
                    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
                    path.chmod(0o600)
                return self.since
        raise DataError(f"{timeout:.0f}s không thấy response danh sách thiết bị trong {self.flows}. "
                        "mitmdump (sniff_api.py) có đang chạy và điện thoại có trỏ proxy về máy này không?")

    def stop(self) -> None:
        pass
