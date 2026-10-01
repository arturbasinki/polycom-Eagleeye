#!/usr/bin/env python3
"""Window texts come from the catalogs and follow the language, without a real window
(a mock Flet page).

    .venv/bin/python tests/test_app_language.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from runner import run  # noqa: E402
from test_engine import make_engine  # noqa: E402

import app as app_module  # noqa: E402
from app import CameraApp  # noqa: E402
from eagleeye import i18n  # noqa: E402
from eagleeye.tracker import TrackerState  # noqa: E402


def test_diagnostics_text_is_translated() -> None:
    state = TrackerState(mode="tracking", pan_state="idle", tilt_state="moving", side="left",
                         shot="MS", auto_zoom=True)
    try:
        i18n.set_language("en")
        english = app_module._diag_text(state)
        i18n.set_language("pl")
        polish = app_module._diag_text(state)
    finally:
        i18n.set_language("en")
    assert "mode" in english and "tracking" in english and "idle" in english and "left" in english
    assert "tryb" in polish and "śledzenie" in polish and "spokój" in polish and "lewy" in polish    # polish: deliberate


def test_diagnostics_text_handles_an_empty_state() -> None:
    text = app_module._diag_text(TrackerState())
    assert "{" not in text and "}" not in text


def test_window_labels_come_from_the_catalog() -> None:
    engine, _ = make_engine()
    engine.start()                      # same pattern as tests/test_preview_click.py
    engine.command("language", "en")
    try:
        ui = CameraApp(MagicMock(), engine, MagicMock())
        assert ui.device_dd.label == "device" and ui.res_dd.label == "resolution"
        assert ui.profile_dd.options[0].text == "talk"
    finally:
        i18n.set_language("en")
        engine.shutdown()


def test_language_switch_rebuilds_the_window_labels() -> None:
    engine, _ = make_engine()
    engine.start()
    engine.command("language", "en")
    try:
        ui = CameraApp(MagicMock(), engine, MagicMock())
        assert ui.device_dd.label == "device"
        ui._on_language_change(SimpleNamespace(control=SimpleNamespace(value="pl")))
        assert ui.device_dd.label == "urządzenie" and ui.profile_dd.options[0].text == "rozmowa"      # polish: deliberate
        assert engine.settings["language"] == "pl"
        ui._on_language_change(SimpleNamespace(control=SimpleNamespace(value="en")))
        assert ui.device_dd.label == "device"
        assert ui.language_dd.value == "en"
    finally:
        i18n.set_language("en")
        engine.shutdown()


def test_rebuild_keeps_the_settings_the_user_chose() -> None:
    engine, _ = make_engine()
    engine.start()
    engine.command("language", "en")
    try:
        ui = CameraApp(MagicMock(), engine, MagicMock())
        engine.settings["tracking"]["profile"] = "presentation"
        ui._rebuild_ui()
        assert ui.profile_dd.value == "presentation"
    finally:
        i18n.set_language("en")
        engine.shutdown()


if __name__ == "__main__":
    run(globals(), "Window language")
