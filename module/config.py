"""Đường dẫn và tham số dùng chung."""
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # thư mục project
DATA = ROOT / "data"
PATTERN_DIR = DATA / "huno_pattern"            # map mẫu của app, commit git

APP_PACKAGE = "com.iot.hunonic"

# Danh sách nhà/thiết bị: hook REST trong APK đã vá (~/Reverse/HunonicApp/mitm/README-direct.md).
# Mỗi lần chạy lấy lại qua CAPTURE_SCRIPT; EXPORTS là nơi script đó ghi response mới nhất.
CAPTURE_SCRIPT = Path("~/Reverse/HunonicApp/mitm/scripts/direct-capture.py").expanduser()
EXPORTS = Path("~/Reverse/HunonicApp/mitm/exports").expanduser()
HOME_ID = "792334"                             # chỉ test 1 nhà
MAX_AGE = timedelta(hours=12)                  # chỉ dùng khi chạy --no-fresh

# Từ điển i18n lấy từ bản decompile — để anchor không phụ thuộc ngôn ngữ app
DECOMPILE = Path("~/Reverse/HunonicApp/4.0.19/js/app").expanduser()
I18N = {
    "vi": DECOMPILE / "features/account/logic/872_user.js",
    "en": DECOMPILE / "core/i18n/logic/873_user.js",
}


def phone_dir(serial: str) -> Path:
    """data/<serial>/ — dữ liệu riêng của từng điện thoại."""
    return DATA / serial
