#!/usr/bin/env python3
"""Loading config.json: camera-head dynamics.

    .venv/bin/python tests/test_config.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from runner import run  # noqa: E402

from eagleeye.config import Store  # noqa: E402


def store_with(settings: dict) -> Store:
    path = Path(tempfile.mkdtemp()) / "config.json"
    path.write_text(json.dumps({"settings": settings, "presets": []}), encoding="utf-8")
    return Store(path)


def test_dynamics_default_is_empty() -> None:
    assert store_with({}).settings["dynamics"] == {}


def test_dynamics_is_loaded() -> None:
    s = store_with({"dynamics": {"vel_speed": 120000.0}})
    assert s.settings["dynamics"] == {"vel_speed": 120000.0}


def test_old_tracking_keys_are_dropped() -> None:
    s = store_with({"tracking": {"kp": 0.9, "settle_time": 0.2, "use_gpu": False, "motion_mode": "rozkaz"}})
    tr = s.settings["tracking"]
    assert "kp" not in tr and "settle_time" not in tr and "motion_mode" not in tr
    assert tr["use_gpu"] is False and tr["profile"] == "talk"


def test_new_tracking_keys_are_kept() -> None:
    s = store_with({"tracking": {"profile": "presentation", "home": [3600, -1800],
                                 "overrides": {"dwell": 0.5}}})
    tr = s.settings["tracking"]
    assert tr["profile"] == "presentation" and tr["home"] == [3600, -1800] and tr["overrides"] == {"dwell": 0.5}


def test_auto_zoom_defaults_on_and_survives_reload() -> None:
    s = store_with({})
    assert s.settings["tracking"]["auto_zoom"] is True
    s.settings["tracking"]["auto_zoom"] = False
    s.save()
    reloaded = Store(s.path)
    assert reloaded.settings["tracking"]["auto_zoom"] is False



def test_select_hold_defaults_to_six_seconds_and_survives_reload() -> None:
    path = Path(tempfile.mkdtemp()) / "config.json"
    s = Store(path)
    assert s.settings["tracking"]["select_hold_s"] == 6.0
    s.settings["tracking"]["select_hold_s"] = 10.0
    s.save()
    assert Store(path).settings["tracking"]["select_hold_s"] == 10.0


def test_language_defaults_to_auto_and_is_loaded() -> None:
    assert store_with({}).settings["language"] == "auto"
    assert store_with({"language": "pl"}).settings["language"] == "pl"


def test_language_setting_reads_config_without_the_store() -> None:
    from eagleeye.config import language_setting
    path = Path(tempfile.mkdtemp()) / "config.json"
    assert language_setting(path) == "auto", "missing file"
    path.write_text("{not json", encoding="utf-8")
    assert language_setting(path) == "auto", "unreadable file"
    path.write_text(json.dumps({"settings": {"language": "pl"}}), encoding="utf-8")
    assert language_setting(path) == "pl"


if __name__ == "__main__":
    run(globals(), "Configuration")
