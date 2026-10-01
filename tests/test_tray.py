#!/usr/bin/env python3
"""Ikona w zasobniku: logika menu (bez GTK) i proces potomny.

    .venv/bin/python tests/test_tray.py
"""

from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from runner import run  # noqa: E402

from eagleeye.trayproc import TrayProcess  # noqa: E402

spec = importlib.util.spec_from_file_location("eagleeye_tray", ROOT / "tray" / "eagleeye_tray.py")
tray = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tray)          # gi importuje dopiero main() - tu wystarczy venv


def test_icon_follows_privacy() -> None:
    assert tray.icon_for({"privacy": True}) == tray.ICON_PRIVACY
    assert tray.icon_for({"privacy": False}) == tray.ICON
    assert tray.ICON.exists() and tray.ICON_PRIVACY.exists()


def test_tooltip_describes_state() -> None:
    text = tray.tooltip({"camera": True, "tracking": True, "profile": "talk", "privacy": False})
    assert "śledzenie" in text and "talk" in text
    assert "prywatność" in tray.tooltip({"privacy": True})
    assert "niepodłączona" in tray.tooltip({"camera": False})


def test_process_starts_and_stops() -> None:
    p = TrayProcess(argv=[sys.executable, "-c", "import time; time.sleep(30)"])
    assert p.start() and p.alive
    p.stop()
    assert not p.alive


def test_crashing_process_is_restarted_once() -> None:
    p = TrayProcess(argv=[sys.executable, "-c", "import sys; sys.exit(3)"], restarts=1)
    p.start()
    time.sleep(1.5)
    assert p.spawns == 2 and not p.alive
    p.stop()


def test_missing_interpreter_is_not_fatal() -> None:
    p = TrayProcess(argv=["/nie/ma/takiego/pythona"])
    assert p.start() is False and not p.alive


if __name__ == "__main__":
    run(globals(), "Ikona w zasobniku")
