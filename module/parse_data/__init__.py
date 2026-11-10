"""Danh sách nhà/thiết bị (lấy mới qua hook mỗi lần chạy) → House; luật hold → leaf trong bộ nhớ."""
from .capture import Capture, LogcatCapture, MitmCapture
from .house import Device, House, HouseDiff, Room, diff_house, load_house, parse_house, save_house
from .rules import HOLD_WHEN, entry_route, hold_allowed, leaf_doc
from .source import DataError, check_fresh, latest_response
