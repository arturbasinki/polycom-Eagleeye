#!/usr/bin/env python3
"""Project rule: code, comments, docstrings, tests and docs are English. Polish may only live
in the Polish catalog and in README.pl.md.

    .venv/bin/python tests/test_code_is_english.py

Catches Polish diacritics only; unaccented Polish needs a human read (see the plan's final sweep).
Lines that deliberately contain Polish test data end with ``# polish: deliberate``.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from runner import run  # noqa: E402

POLISH = re.compile("[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]")  # polish: deliberate
ALLOWED_LINE = re.compile(r"polish: deliberate|^\s*Comment\[pl\]=|© 20\d\d Artur Bas")
SUFFIXES = {".py", ".sh", ".md", ".txt", ".json", ".svg"}
SKIP_DIRS = {".git", ".venv", "__pycache__", "docs", "captures", "models", "resources", "locales"}
SKIP_FILES = {"README.pl.md", "config.json"}      # config.json: the author's live settings, never published with Polish


def sources():
    for path in sorted(ROOT.rglob("*")):
        rel = path.relative_to(ROOT)
        if (path.is_file() and path.suffix in SUFFIXES and path.name not in SKIP_FILES
                and not any(part in SKIP_DIRS or part.startswith(".") for part in rel.parts)):
            yield path, rel


def test_no_polish_outside_the_polish_catalog() -> None:
    offenders = []
    for path, rel in sources():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if POLISH.search(line) and not ALLOWED_LINE.search(line):
                offenders.append(f"{rel}:{number}: {line.strip()[:90]}")
    assert not offenders, f"{len(offenders)} Polish line(s):\n  " + "\n  ".join(offenders[:40])


def test_the_scan_sees_the_files_it_should() -> None:
    names = {rel.name for _, rel in sources()}
    assert {"app.py", "director.py", "install.sh", "README.md", "test_engine.py"} <= names
    assert "pl.json" not in names and "README.pl.md" not in names


if __name__ == "__main__":
    run(globals(), "Code is English")
