"""State machine điều phối: IDLE → DISCOVERY → ACTIVE.

IDLE      lấy danh sách nhà/thiết bị MỚI qua hook (mở lại app), ghép map: core + root_type + feature
          (loại chưa có pattern → leaf trong bộ nhớ), so toạ độ đã lưu của máy này
DISCOVERY học các cạnh core còn thiếu; cạnh vào thiết bị / feature thì học dọc đường khi goto
ACTIVE    goto() theo đường ngắn nhất; gặp cạnh chưa học → DISCOVERY tạm thời rồi quay lại

Chạy:  .venv/bin/python -m module.scout [--no-fresh] <đích> [đích ...]
       đích = id node, hoặc một đoạn chữ khớp duy nhất một node (vd "infoDeviceCommonView[Ổ cắm sk01]")
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from enum import Enum, auto

from . import config
from . import interact as adb
from .parse_data import Capture, LogcatCapture, check_fresh, latest_response, parse_house
from .ui_map import Edge, Lexicon, Lost, Map, Navigator, Resolved, instantiate, load_docs
from .ui_map.locate import learns_band

log = logging.getLogger("scout")


class State(Enum):
    IDLE = auto()
    DISCOVERY = auto()
    ACTIVE = auto()


ALLOWED = {
    State.IDLE: {State.DISCOVERY, State.ACTIVE},
    State.DISCOVERY: {State.ACTIVE, State.IDLE},
    State.ACTIVE: {State.DISCOVERY, State.IDLE},
}


@dataclass
class Report:
    warnings: list[str] = field(default_factory=list)
    devices: int = 0
    leaves: list[str] = field(default_factory=list)       # màn vào của từng thiết bị
    resolved: list[str] = field(default_factory=list)
    anchors: dict[str, dict] = field(default_factory=dict)
    failed: list[tuple[str, str]] = field(default_factory=list)
    unexplored: list[str] = field(default_factory=list)   # cạnh tới màn chưa biết cách nhận ra
    pruned: list[str] = field(default_factory=list)
    tiles: list[str] = field(default_factory=list)        # cạnh hold vào ô thiết bị vừa ghi lại toạ độ
    transitions: list[str] = field(default_factory=list)


class Scout:
    def __init__(self, serial: str | None = None):
        if serial:
            adb.set_serial(serial)
        self.serial = adb.serial()
        self.state = State.IDLE
        self.report = Report()
        self.graph: Map | None = None
        self.nav: Navigator | None = None

    def _go(self, new: State, why: str) -> None:
        if new not in ALLOWED[self.state]:
            raise RuntimeError(f"không được chuyển {self.state.name} → {new.name}")
        line = f"{self.state.name} → {new.name}: {why}"
        log.info(line)
        self.report.transitions.append(line)
        self.state = new

    # ---- IDLE ----

    def _fetch_house(self, fresh: bool):
        """Danh sách nhà/thiết bị: fresh → mở lại app qua hook rồi lấy response mới (mặc định)."""
        if fresh:                                # không có script collector (máy khác) → đọc thẳng logcat
            cap = (Capture(config.CAPTURE_SCRIPT, self.serial) if config.CAPTURE_SCRIPT.exists()
                   else LogcatCapture(config.EXPORTS, self.serial))
            t = time.monotonic()
            cap.start()
            try:
                adb.force_stop(config.APP_PACKAGE)
                adb.launch(config.APP_PACKAGE)
                cap.wait_list()
            finally:
                cap.stop()
            log.info("danh sách thiết bị mới qua hook: %.1f s", time.monotonic() - t)
        resp, observed = latest_response(config.EXPORTS)
        if not fresh and (warn := check_fresh(observed, config.MAX_AGE)):
            self.report.warnings.append(warn)
        return parse_house(resp, config.HOME_ID, observed.isoformat())

    def load(self, fresh: bool) -> None:
        """IDLE: danh sách nhà/thiết bị → map + toạ độ đã học của máy này. Không chạm màn hình
        (trừ fresh: mở lại app để lấy danh sách qua hook). Gọi lại được để làm mới map."""
        r = self.report = Report(transitions=self.report.transitions)
        house = self._fetch_house(fresh)
        r.devices = len(house.devices)
        if house.duplicates:
            r.warnings.append(f"tên trùng, đã loại khỏi map: {', '.join(house.duplicates)}")

        profile = adb.device_profile(config.APP_PACKAGE)
        pdir = config.phone_dir(self.serial)
        pdir.mkdir(parents=True, exist_ok=True)
        (pdir / "profile.json").write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")

        self.graph, glyphs = instantiate(load_docs(config.PATTERN_DIR, house.root_types), house)
        r.leaves = sorted(n.id for n in self.graph.nodes.values() if n.file.startswith("root_type/")
                          and any(e.to == n.id for e in self.graph.edges() if e.file == "core"))
        self.res = Resolved(pdir / "huno_pattern", profile)
        r.pruned = self.res.prune(self.graph)
        self.res.apply_costs(self.graph)
        self.nav = Navigator(self.graph, self.res, Lexicon(config.I18N), glyphs)

    def start(self, fresh: bool = True) -> Report:
        self.load(fresh)
        r = self.report
        if adb.current_package() != config.APP_PACKAGE:
            raise Lost(f"app {config.APP_PACKAGE} không ở màn hình trước — mở app rồi chạy lại")
        missing, r.unexplored = self.plan()
        unlearned = self.unlearned()
        if missing or unlearned or fresh:
            self._go(State.DISCOVERY, f"core: thiếu toạ độ {len(missing)} cạnh, chưa học title {len(unlearned)} màn"
                     + (", quét lại ô thiết bị" if fresh else ""))
            if missing:
                done, failed = self.nav.discover(missing)
                r.resolved += [e.id for e in done]
                r.failed += [(e.id, why) for e, why in failed]
            self._learn_anchors()
            if fresh:
                self._scan_tiles()
        self._go(State.ACTIVE, f"{len(r.resolved)} cạnh mới, {len(r.anchors)} title mới, {len(r.tiles)} ô thiết bị, "
                 f"{len(r.failed)} lỗi")
        return r

    def usable(self, e: Edge) -> bool:
        """Cạnh đi được: hai đầu đều là màn đã biết cách nhận ra (đã học toạ độ hay chưa đều được)."""
        return self.graph.nodes[e.src].explored and self.graph.nodes[e.to].explored

    def plan(self) -> tuple[list[Edge], list[str]]:
        """(cạnh core cần học lúc khởi động, cạnh tạm bỏ vì màn đích chưa biết cách nhận ra).

        Chỉ cạnh giữa hai màn core. Cạnh vào thiết bị/feature học dọc đường khi goto; cạnh ra từ
        popup tự bật (không có cạnh vào, vd popup.switchHouse) học khi popup xuất hiện.
        """
        n = self.graph.nodes
        reachable = {e.to for e in self.graph.edges()} | {"home"}
        missing, unexplored = [], []
        for e in self.graph.edges():
            if not self.usable(e):
                unexplored.append(e.id)
            elif (n[e.src].file == n[e.to].file == "core" and e.src in reachable
                  and self.res.get(e) is None):
                missing.append(e)
        return missing, unexplored

    def unlearned(self) -> list[str]:
        """Màn core đã khám nhưng chưa học vị trí title trên máy này (màn thiết bị học khi đi tới).

        Bỏ màn không có cạnh vào (popup tự bật, vd popup.switchHouse): không đi tới được để học,
        học khi nó tự xuất hiện — giống plan().
        """
        reachable = {e.to for e in self.graph.edges()} | {"home"}
        return [n.id for n in self.graph.nodes.values()
                if n.file == "core" and n.explored and learns_band(n) and n.id in reachable
                and self.res.get_anchor(n) is None]

    def _learn_anchors(self) -> None:
        for nid in self.unlearned():
            try:
                self.nav.goto(nid, self.usable)
                if rec := self.nav.learn_anchor(nid):
                    self.report.anchors[nid] = {"text": rec["text"], "band": rec["band"]}
                else:
                    self.report.failed.append((nid, "không thấy title trên màn"))
            except (Lost, LookupError) as err:
                self.report.failed.append((nid, f"học title: {err}"))

    def _scan_tiles(self) -> None:
        """Vị trí ô thiết bị đổi theo thiết bị thêm/bớt, trạng thái → mỗi lần discovery đọc lại màn từng phòng."""
        for room in self.graph.nodes.values():
            holds = [e for e in room.edges if e.action.gesture == "hold" and e.action.target and e.action.target.desc]
            if room.file != "core" or not holds:
                continue
            try:
                self.nav.goto(room.id, self.usable)
                self.report.tiles += self.nav.scan_tiles(holds)
            except (Lost, LookupError) as err:
                self.report.failed.append((room.id, f"quét ô thiết bị: {err}"))

    # ---- ACTIVE ----

    def resolve_target(self, name: str) -> str:
        if name in self.graph.nodes:
            return name
        hits = [n for n in self.graph.nodes if name in n]
        if len(hits) != 1:
            raise KeyError(f"{name!r} khớp {len(hits)} node: {hits[:8]}")
        return hits[0]

    def goto(self, dst: str) -> str:
        if self.state is not State.ACTIVE:
            raise RuntimeError(f"goto chỉ dùng ở ACTIVE (đang {self.state.name})")
        dst = self.resolve_target(dst)
        cur = self.nav.cur or self.nav.recover()
        if cur is None:
            raise Lost("không nhận ra màn hiện tại (popup lạ?) — xem màn hình")
        path = self.graph.path(cur, dst, ok=self.usable)
        new = [e for e in path if self.res.get(e) is None]
        if new:
            self._go(State.DISCOVERY, f"đường tới {dst} có {len(new)} cạnh chưa học → học dọc đường")
        try:
            return self.nav.goto(dst, self.usable)
        finally:
            if self.state is State.DISCOVERY:
                self._go(State.ACTIVE, "đã tới" if self.nav.cur == dst else "dừng")

    def stop(self, why: str = "dừng") -> None:
        if self.state is not State.IDLE:
            self._go(State.IDLE, why)


def main(argv: list[str]) -> None:
    ap = argparse.ArgumentParser(prog="python -m module.scout", description=__doc__.split("\n\n")[0])
    ap.add_argument("targets", nargs="*", help="màn cần tới, lần lượt")
    ap.add_argument("--no-fresh", action="store_true", help="dùng danh sách thiết bị export lần trước")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s.%(msecs)03d %(message)s", datefmt="%H:%M:%S",
                        stream=sys.stderr)
    for noisy in ("module.ui_map.pattern", "module.parse_data.rules"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    t0 = time.monotonic()
    s = Scout()
    rep = s.start(fresh=not args.no_fresh)
    log.info("sẵn sàng sau %.1f s: %d thiết bị, %d leaf", time.monotonic() - t0, rep.devices, len(rep.leaves))
    for dst in args.targets:
        t = time.monotonic()
        s.goto(dst)
        log.info("✅ tới %s sau %.1f s", s.nav.cur, time.monotonic() - t)
    print(json.dumps({"state": s.state.name, "pointer": s.nav.pointer(), "warnings": rep.warnings,
                      "failed": rep.failed}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main(sys.argv[1:])
