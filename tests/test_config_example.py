#!/usr/bin/env python3
"""config.example.json: a template for everyone else. The live config.json is not in git, so
the example must always be exactly what a fresh application would write.

    .venv/bin/python tests/test_config_example.py
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from runner import run  # noqa: E402

from eagleeye.config import DEFAULTS, Store  # noqa: E402

EXAMPLE = ROOT / "config.example.json"
REGENERATE = ('.venv/bin/python -c "from pathlib import Path; from eagleeye.config import Store; '
              "s = Store(Path('/nonexistent/config.json')); s.path = Path('config.example.json'); s.save()\"")


def fresh_store() -> Store:
    return Store(Path(tempfile.mkdtemp()) / "config.json")


def test_the_example_is_what_a_fresh_application_writes() -> None:
    store = fresh_store()
    store.save()
    written = json.loads(store.path.read_text(encoding="utf-8"))
    assert json.loads(EXAMPLE.read_text(encoding="utf-8")) == written, \
        f"config.example.json is out of date; regenerate it with:\n  {REGENERATE}"


def test_the_example_loads_without_losing_a_key() -> None:
    path = Path(tempfile.mkdtemp()) / "config.json"
    shutil.copy(EXAMPLE, path)
    store = Store(path)
    assert store.settings == DEFAULTS and store.presets == []


def test_the_example_carries_nothing_from_a_particular_room() -> None:
    tracking = json.loads(EXAMPLE.read_text(encoding="utf-8"))["settings"]["tracking"]
    assert tracking["home"] is None and tracking["last_azimuth"] is None
    assert tracking["record"] is False
    assert json.loads(EXAMPLE.read_text(encoding="utf-8"))["settings"]["dynamics"] == {}, \
        "calibration lives in code (head_model.Dynamics); the example must not shadow it"


def test_the_application_works_without_a_config_file() -> None:
    store = Store(Path(tempfile.mkdtemp()) / "missing.json")
    assert store.settings == DEFAULTS and not store.path.exists()
    store.save()
    assert store.path.exists(), "the first save creates the file"


if __name__ == "__main__":
    run(globals(), "Config example")
