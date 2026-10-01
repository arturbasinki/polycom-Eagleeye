#!/usr/bin/env python3
"""Privacy: the slate immediately, the lens down, a return to the previous state.

    .venv/bin/python tests/test_privacy.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from runner import run  # noqa: E402

from eagleeye.privacy import Privacy  # noqa: E402


class Log(list):
    pass


class FakeVcam:
    def __init__(self, log: Log) -> None:
        self.log = log

    def set_privacy(self, on: bool) -> None:
        self.log.append(("vcam", on))


class FakeTracker:
    def __init__(self, log: Log, enabled: bool = True) -> None:
        self.log = log
        self.enabled = enabled

    def position(self):
        return (36000.0, 7200.0)

    def tilt_min(self) -> float:
        return -108000.0

    def set_enabled(self, on: bool) -> None:
        self.enabled = on
        self.log.append(("sledzenie", on))

    def move_to(self, pan=None, tilt=None) -> bool:
        if self.enabled:
            return False
        self.log.append(("ruch", pan, tilt))
        return True


def test_enable_shows_card_first_then_parks_head() -> None:
    log = Log()
    p = Privacy(FakeVcam(log))
    p.enable(FakeTracker(log))
    assert p.active
    assert log == [("vcam", True), ("sledzenie", False), ("ruch", None, -108000.0)]


def test_disable_restores_pose_tracking_and_live_image() -> None:
    log = Log()
    p = Privacy(FakeVcam(log))
    tr = FakeTracker(log)
    p.enable(tr)
    log.clear()
    p.disable(tr)
    assert not p.active
    assert log == [("ruch", 36000.0, 7200.0), ("sledzenie", True), ("vcam", False)]


def test_tracking_stays_off_if_it_was_off() -> None:
    log = Log()
    p = Privacy(FakeVcam(log))
    tr = FakeTracker(log, enabled=False)
    p.enable(tr)
    p.disable(tr)
    assert ("sledzenie", True) not in log


def test_without_camera_only_the_card_changes() -> None:
    log = Log()
    p = Privacy(FakeVcam(log))
    p.enable(None)
    p.disable(None)
    assert log == [("vcam", True), ("vcam", False)]


def test_enable_twice_keeps_first_saved_pose() -> None:
    log = Log()
    p = Privacy(FakeVcam(log))
    tr = FakeTracker(log)
    p.enable(tr)
    p.enable(tr)
    assert log.count(("vcam", True)) == 1


if __name__ == "__main__":
    run(globals(), "Privacy")
