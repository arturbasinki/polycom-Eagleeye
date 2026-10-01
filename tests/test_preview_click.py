#!/usr/bin/env python3
"""Kliknięcie w podgląd: okno -> klatka -> wybór osoby. Bez okna: atrapa strony Fleta.

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
    engine.command("sledzenie", "wl")
    assert _wait_until(lambda: len(engine.tracker.state.tracks) == 2)
    return engine, CameraApp(MagicMock(), engine, MagicMock())


def test_tap_on_a_person_selects_them() -> None:
    engine, ui = _app_with_two_people()
    try:
        ui._overlay_size = (1280.0, 720.0)            # klatka 640x360 -> skala 2, bez pasów
        ui._on_preview_tap(_tap(2 * 220, 2 * 80))     # wewnątrz ramki prawej osoby
        assert _wait_until(lambda: engine.state()["wybor"]["stan"] == "wybrana")
    finally:
        engine.shutdown()


def test_tap_in_the_side_bars_or_empty_space_selects_nobody() -> None:
    engine, ui = _app_with_two_people()
    try:
        ui._overlay_size = (2000.0, 720.0)            # pas 360 px z lewej i z prawej
        ui._on_preview_tap(_tap(100, 160))
        ui._on_preview_tap(_tap(360 + 2 * 150, 2 * 80))   # w obrazie, ale między osobami
        time.sleep(0.3)
        assert engine.state()["wybor"]["stan"] == "auto"
    finally:
        engine.shutdown()


def test_tap_is_ignored_without_tracking() -> None:
    engine, ui = _app_with_two_people()
    try:
        engine.command("sledzenie", "wyl")
        ui._overlay_size = (1280.0, 720.0)
        ui._on_preview_tap(_tap(440, 160))
        assert engine.state()["wybor"]["stan"] == "auto"
        ui._on_preview_tap(SimpleNamespace(local_position=None))     # brak pozycji: bez wyjątku
    finally:
        engine.shutdown()


if __name__ == "__main__":
    run(globals(), "Kliknięcie w podgląd")
