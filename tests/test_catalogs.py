#!/usr/bin/env python3
"""Catalog consistency: same keys and placeholders in every language, and every literal key
used in the source exists.

    .venv/bin/python tests/test_catalogs.py
"""

from __future__ import annotations

import ast
import importlib.util
import json
import string
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from runner import run  # noqa: E402

LOCALES = ROOT / "eagleeye" / "locales"
KEY_CALLS = {"t", "msg", "Message", "LocalizedError"}     # first positional argument is a key
SOURCES = ([ROOT / "app.py"] + sorted((ROOT / "eagleeye").glob("*.py"))
           + sorted((ROOT / "tray").glob("*.py")) + sorted((ROOT / "tools").glob("*.py")))

from eagleeye import director, framing  # noqa: E402

# Keys built at runtime (``t(f"director.mode.{mode}")``): prefix -> the values it is built from.
# Tasks that introduce a family extend this table.
_spec = importlib.util.spec_from_file_location("live_session", ROOT / "tools" / "live_session.py")
live_session = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(live_session)       # importing it touches no hardware: main() does that

DYNAMIC_FAMILIES: dict[str, list[str]] = {
    "director.mode.": [director.TRACKING, director.SEARCHING, director.LOST, director.WAITING],
    "director.axis.": [director.IDLE, director.ALERT, director.MOVING, director.FOLLOWING, director.BRAKING],
    "framing.side.": [framing.CENTER, framing.LEFT, framing.RIGHT],
    "profile.": ["talk", "presentation"],
    "shot.": ["CU", "MCU", "MS"],
    "live_session.cue.": sorted({cue for script in live_session.SCRIPTS.values() for _, cue in script}),
}


def load(code: str) -> dict:
    return json.loads((LOCALES / f"{code}.json").read_text(encoding="utf-8"))


def codes() -> list[str]:
    return sorted(p.stem for p in LOCALES.glob("*.json"))


def fields(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name is not None}


def test_english_catalog_exists() -> None:
    assert "en" in codes() and load("en")["_name"] == "English"


def test_every_language_has_a_native_name() -> None:
    for code in codes():
        assert isinstance(load(code).get("_name"), str) and load(code)["_name"], code


def test_all_values_are_non_empty_strings() -> None:
    for code in codes():
        for key, value in load(code).items():
            assert isinstance(value, str) and value.strip(), (code, key)


def test_every_language_has_exactly_the_english_keys() -> None:
    en = set(load("en"))
    for code in codes():
        keys = set(load(code))
        assert not (en - keys), f"{code} is missing: {sorted(en - keys)}"
        assert not (keys - en), f"{code} has keys absent from en: {sorted(keys - en)}"


def test_placeholders_match_english() -> None:
    en = load("en")
    for code in codes():
        for key, text in load(code).items():
            if key in en:
                assert fields(text) == fields(en[key]), (code, key, text)


def _literal_keys(path: Path) -> list[tuple[int, str]]:
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
        first = node.args[0]
        if name in KEY_CALLS and isinstance(first, ast.Constant) and isinstance(first.value, str):
            found.append((node.lineno, first.value))
    return found


def test_literal_keys_used_in_source_exist() -> None:
    en = load("en")
    missing = []
    for path in SOURCES:
        if path.name == "i18n.py":
            continue
        for line, key in _literal_keys(path):
            if key not in en:
                missing.append(f"{path.relative_to(ROOT)}:{line} {key}")
    assert not missing, "unknown catalog keys:\n  " + "\n  ".join(missing)


def test_dynamic_key_families_are_complete() -> None:
    en = load("en")
    missing = [f"{prefix}{value}" for prefix, values in DYNAMIC_FAMILIES.items()
               for value in values if f"{prefix}{value}" not in en]
    assert not missing, f"missing dynamic keys: {missing}"


if __name__ == "__main__":
    run(globals(), "Catalogs")
