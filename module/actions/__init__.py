"""Tương tác trong feature của thiết bị (chạy trên Scout đã ACTIVE): hẹn giờ, khoá công tắc, chia sẻ,
chế độ nhấn nhả, hẹn giờ nhanh, lặp tuần hoàn, lịch sử, đầu vào AC/DC, thông tin chung."""
from .cycle import add_cycle, delete_cycle, edit_cycle, list_cycles
from .history import history
from .info import general_info
from .inputs import get_inputs, set_input_ac, set_input_dc
from .lock import get_lock, set_lock
from .press import delete_quick_timer, get_press_mode, get_quick_timer, set_press_mode, set_quick_timer
from .share import device_perms, edit_share, share, shared_users, unshare
from .timer import add_timer, delete_timer, edit_timer, list_timers
from .ui import ActionError
