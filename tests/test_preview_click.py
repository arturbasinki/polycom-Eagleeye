#!/usr/bin/env python3
"""Preview click: window -> frame -> person selection. Without a window: a mock Flet page.

    .venv/bin/python tests/test_preview_click.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fakes import TwoPeople  # noqa: E402
from runner import run  # noqa: E402
from test_engine import make_engine  # noqa: E402

from app import CameraApp  # noqa: E402


def _tap(x: float, y: float):
    return SimpleNamespace(local_position=SimpleNamespace(x=x, y=y))


def _wait_until(cond, timeout: float = 3.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def _app_with_two_people():
    engine, _ = make_engine(perception=TwoPeople)
    engine.start()
    engine.command("tracking", "on")
    assert _wait_until(lambda: len(engine.tracker.state.tracks) == 2)
    return engine, CameraApp(MagicMock(), engine, MagicMock())


def test_tap_on_a_person_selects_them() -> None:
    engine, ui = _app_with_two_people()
    try:
        ui._overlay_size = (1280.0, 720.0)            # frame 640x360 -> scale 2, no bars
        ui._on_preview_tap(_tap(2 * 220, 2 * 80))     # inside the right person's box
        assert _wait_until(lambda: engine.state()["selection"]["state"] == "selected")
    finally:
        engine.shutdown()


def test_tap_in_the_side_bars_or_empty_space_selects_nobody() -> None:
    engine, ui = _app_with_two_people()
    try:
        ui._overlay_size = (2000.0, 720.0)            # a 360 px bar on the left and on the right
        ui._on_preview_tap(_tap(100, 160))
        ui._on_preview_tap(_tap(360 + 2 * 150, 2 * 80))   # in the image, but between the people
        time.sleep(0.3)
        assert engine.state()["selection"]["state"] == "auto"
    finally:
        engine.shutdown()


def test_tap_is_ignored_without_tracking() -> None:
    engine, ui = _app_with_two_people()
    try:
        engine.command("tracking", "off")
        ui._overlay_size = (1280.0, 720.0)
        ui._on_preview_tap(_tap(440, 160))
        assert engine.state()["selection"]["state"] == "auto"
        ui._on_preview_tap(SimpleNamespace(local_position=None))     # no position: no exception
    finally:
        engine.shutdown()


if __name__ == "__main__":
    run(globals(), "Preview click")
