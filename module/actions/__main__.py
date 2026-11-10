"""Chạy thử một tương tác từ dòng lệnh (tự khởi động Scout --no-fresh). In kết quả JSON.

ANDROID_SERIAL=2fc3878f .venv/bin/python -m module.actions <lệnh> --device "Công tắc " [tham số]
  lock-get | lock-set MODE (device|app|both|none)
  timer-list | timer-delete HH:MM
  timer-add  [--at HH:MM] [--action on|off|child_lock|child_unlock] [--kind time|sunrise|sunset]
             [--repeat once|weekly|monthly] [--days mon,tue,…] [--monthday N] [--last-day] [--date YYYY-MM-DD]
             [--no-online] [--no-save]
  timer-edit HH:MM [cùng tham số như timer-add, chỉ cái được truyền mới đổi]
  share (--phone SĐT | --email EMAIL) [--perms control,timer,…] [--no-submit]
  share-edit SĐT|EMAIL --perms control,timer,…   |   unshare SĐT|EMAIL
  press-get | press-set MM:SS (00:00 = tắt)
  quick-get | quick-set PHÚT [--action on|off] | quick-delete
  history | general-info
  inputs-get | input-ac-set on|off | input-dc-set green|red --action on|off|none
  cycle-list | cycle-delete [N]
  cycle-add  [--on MM:SS] [--off MM:SS] [--start HH:MM --end HH:MM] [--weekly on|off] [--days mon,…]
             [--date YYYY-MM-DD (cần --weekly off)] [--no-save]   (có start/end/weekly/days/date → Giới hạn thời gian)
  cycle-edit [N] [cùng tham số] [--mode forever|limit]     N = thứ tự dòng, 0 = đầu
"""
import argparse
import json
import logging
import sys

from ..scout import Scout
from . import (general_info, get_inputs, set_input_ac, set_input_dc, add_cycle, add_timer, delete_cycle, delete_quick_timer, edit_cycle, list_cycles, delete_timer, edit_share, edit_timer, get_lock, get_press_mode,
               get_quick_timer, history, list_timers, set_lock, set_press_mode, set_quick_timer, share, unshare)


def main(argv: list[str]) -> None:
    ap = argparse.ArgumentParser(prog="python -m module.actions")
    ap.add_argument("cmd")
    ap.add_argument("arg", nargs="?")
    ap.add_argument("--device", required=True)
    for opt in ("--at", "--action", "--kind", "--repeat", "--days", "--date", "--phone", "--email", "--perms",
                "--on", "--off", "--start", "--end"):
        ap.add_argument(opt)
    ap.add_argument("--monthday", type=int)
    ap.add_argument("--last-day", action="store_true")
    ap.add_argument("--no-online", action="store_true")
    ap.add_argument("--no-save", action="store_true")
    ap.add_argument("--no-submit", action="store_true")
    ap.add_argument("--weekly", choices=["on", "off"])
    ap.add_argument("--mode", choices=["forever", "limit"])
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s.%(msecs)03d %(message)s", datefmt="%H:%M:%S")
    for noisy in ("module.ui_map.pattern", "module.parse_data.rules"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    s = Scout()
    s.start(fresh=False)
    days = a.days.split(",") if a.days else None
    form = {k: v for k, v in dict(action=a.action, kind=a.kind, repeat=a.repeat, days=days, monthday=a.monthday,
                                  date=a.date).items() if v is not None}
    if a.last_day:
        form["last_day"] = True
    if a.cmd == "lock-get":
        out = get_lock(s, a.device)
    elif a.cmd == "lock-set":
        out = set_lock(s, a.device, a.arg)
    elif a.cmd == "timer-list":
        out = list_timers(s, a.device)
    elif a.cmd == "timer-add":
        out = add_timer(s, a.device, at=a.at, run_online=not a.no_online, save=not a.no_save, **form)
    elif a.cmd == "timer-edit":
        if a.at:
            form["at"] = a.at
        if a.no_online:
            form["run_online"] = False
        out = edit_timer(s, a.device, a.arg, **form)
    elif a.cmd == "timer-delete":
        out = delete_timer(s, a.device, a.arg)
    elif a.cmd == "share":
        out = share(s, a.device, phone=a.phone, email=a.email,
                    perms=a.perms.split(",") if a.perms else None, submit=not a.no_submit)
    elif a.cmd == "share-edit":
        out = edit_share(s, a.device, a.arg, a.perms.split(","))
    elif a.cmd == "unshare":
        out = unshare(s, a.device, a.arg)
    elif a.cmd == "press-get":
        out = get_press_mode(s, a.device)
    elif a.cmd == "press-set":
        out = set_press_mode(s, a.device, a.arg)
    elif a.cmd == "quick-get":
        out = get_quick_timer(s, a.device)
    elif a.cmd == "quick-set":
        out = set_quick_timer(s, a.device, int(a.arg), a.action or "on")
    elif a.cmd == "quick-delete":
        out = delete_quick_timer(s, a.device)
    elif a.cmd == "history":
        out = history(s, a.device)
    elif a.cmd == "general-info":
        out = general_info(s, a.device)
    elif a.cmd == "inputs-get":
        out = get_inputs(s, a.device)
    elif a.cmd == "input-ac-set":
        out = set_input_ac(s, a.device, a.arg == "on")
    elif a.cmd == "input-dc-set":
        out = set_input_dc(s, a.device, a.arg, a.action)
    elif a.cmd.startswith("cycle-"):
        cyc = {k: v for k, v in dict(on=a.on, off=a.off, start=a.start, end=a.end, days=days, date=a.date,
                                     weekly=None if a.weekly is None else a.weekly == "on",
                                     limit=None if a.mode is None else a.mode == "limit").items() if v is not None}
        n = int(a.arg or 0)
        if a.cmd == "cycle-list":
            out = list_cycles(s, a.device)
        elif a.cmd == "cycle-add":
            cyc.pop("limit", None)
            out = add_cycle(s, a.device, save=not a.no_save, **cyc)
        elif a.cmd == "cycle-edit":
            out = edit_cycle(s, a.device, n, **cyc)
        elif a.cmd == "cycle-delete":
            out = delete_cycle(s, a.device, n)
        else:
            sys.exit(f"lệnh không có: {a.cmd}")
    else:
        sys.exit(f"lệnh không có: {a.cmd}")
    print(json.dumps(out, ensure_ascii=False, indent=2))


main(sys.argv[1:])
