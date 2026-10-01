#!/usr/bin/env python3
"""Tray icon: menu logic (without GTK) and the child process.

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

from eagleeye import i18n  # noqa: E402
from eagleeye.trayproc import TrayProcess  # noqa: E402

spec = importlib.util.spec_from_file_location("eagleeye_tray", ROOT / "tray" / "eagleeye_tray.py")
tray = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tray)          # gi is imported only by main() - the venv is enough here


def test_icon_follows_privacy() -> None:
    assert tray.icon_for({"privacy": True}) == tray.ICON_PRIVACY
    assert tray.icon_for({"privacy": False}) == tray.ICON
    assert tray.ICON.exists() and tray.ICON_PRIVACY.exists()


def test_tooltip_describes_state_in_both_languages() -> None:
    state = {"camera": True, "tracking": True, "profile": "talk", "privacy": False}
    try:
        i18n.set_language("en")
        text = tray.tooltip(state)
        assert "tracking on" in text and "talk" in text
        assert "privacy" in tray.tooltip({"privacy": True})
        assert "not connected" in tray.tooltip({"camera": False})
        i18n.set_language("pl")
        text = tray.tooltip(state)
        assert "śledzenie włączone" in text and "rozmowa" in text    # polish: deliberate
        assert "prywatność" in tray.tooltip({"privacy": True})    # polish: deliberate
    finally:
        i18n.set_language("en")


def test_tooltip_survives_an_unknown_profile() -> None:
    assert "weird" in tray.tooltip({"camera": True, "tracking": False, "profile": "weird"})


def test_menu_labels_follow_the_language() -> None:
    try:
        i18n.set_language("en")
        assert tray.labels()["quit"] == "Quit"
        i18n.set_language("pl")
        assert tray.labels()["quit"] == "Zakończ"    # polish: deliberate
    finally:
        i18n.set_language("en")


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
    p = TrayProcess(argv=["/no/such/python"])
    assert p.start() is False and not p.alive


if __name__ == "__main__":
    run(globals(), "Tray icon")
