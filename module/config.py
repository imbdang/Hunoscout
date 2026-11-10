"""Đường dẫn và tham số dùng chung."""
from datetime import timedelta
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # thư mục project
DATA = ROOT / "data"
PATTERN_DIR = DATA / "huno_pattern"            # map mẫu của app, commit git

APP_PACKAGE = "com.iot.hunonic"

# Danh sách nhà/thiết bị: hook REST trong APK đã vá (~/Reverse/HunonicApp/mitm/README-direct.md).
# Mỗi lần chạy lấy lại qua CAPTURE_SCRIPT; EXPORTS là nơi script đó ghi response mới nhất.
CAPTURE_SCRIPT = Path("~/Reverse/HunonicApp/mitm/scripts/direct-capture.py").expanduser()
EXPORTS = Path("~/Reverse/HunonicApp/mitm/exports").expanduser()
# App không có hook → danh sách lấy từ flows.jsonl của mitmdump sniff_api.py (HunonicMitm)
MITM_FLOWS = Path(os.environ.get("MITM_EVIDENCE", "~/Project/runtime_evidence/api_sniff")).expanduser() / "flows.jsonl"
HOME_ID = "792334"                             # nhà mặc định khi máy chưa ghi nhà đang chọn (data/<serial>/home.json)
MAX_AGE = timedelta(hours=12)                  # chỉ dùng khi chạy --no-fresh

# Từ điển i18n trích từ bundle của app (nguồn: SOURCE.txt cùng thư mục) — để anchor không phụ thuộc ngôn ngữ app
I18N_DIR = Path("~/ReverseProject/HunonicApp/4.0.23/i18n").expanduser()
I18N = {"vi": I18N_DIR / "vi.js", "en": I18N_DIR / "en.js"}


def phone_dir(serial: str) -> Path:
    """data/<serial>/ — dữ liệu riêng của từng điện thoại."""
    return DATA / serial


def current_home(serial: str) -> str:
    """Id nhà đang chọn trên app của máy này (action đổi nhà ghi vào data/<serial>/home.json); chưa có → HOME_ID."""
    try:
        return str(json.loads((phone_dir(serial) / "home.json").read_text(encoding="utf-8"))["id"])
    except (OSError, ValueError, KeyError):
        return HOME_ID


def set_current_home(serial: str, home_id: str, name: str) -> None:
    p = phone_dir(serial) / "home.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"id": home_id, "name": name}, ensure_ascii=False, indent=2), encoding="utf-8")
