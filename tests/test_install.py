#!/usr/bin/env python3
"""Instalator: składnia, tryb --dry-run (nic nie zmienia), shellcheck, gdy jest.

    .venv/bin/python tests/test_install.py
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from runner import run  # noqa: E402

from eagleeye.i18n import translate  # noqa: E402

SCRIPTS = [ROOT / "install.sh", ROOT / "uninstall.sh"]


def test_scripts_have_valid_bash_syntax() -> None:
    for script in SCRIPTS:
        res = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
        assert res.returncode == 0, f"{script.name}: {res.stderr}"


def test_shellcheck_when_available() -> None:
    if shutil.which("shellcheck") is None:
        print("    POMINIĘTY: brak shellcheck")
        return
    res = subprocess.run(["shellcheck", *map(str, SCRIPTS)], capture_output=True, text=True)
    assert res.returncode == 0, res.stdout


def dry_run(script: Path, locale: str = "en_US.UTF-8") -> tuple[subprocess.CompletedProcess, Path]:
    home = Path(tempfile.mkdtemp())
    # In-memory backend: gsettings reads no real settings and creates no files in HOME.
    env = dict(os.environ, HOME=str(home), XDG_DATA_HOME=str(home / ".local/share"),
               GSETTINGS_BACKEND="memory", LC_ALL=locale)
    res = subprocess.run(["bash", str(script), "--dry-run"], capture_output=True, text=True, env=env, timeout=60)
    return res, home


STEP_KEYS = ["installer.step.packages", "installer.step.module", "installer.step.python",
             "installer.step.model", "installer.step.launcher", "installer.step.placeholder",
             "installer.step.shortcut", "installer.step.done"]


def test_install_dry_run_lists_every_step_in_both_languages() -> None:
    for language, locale in (("en", "en_US.UTF-8"), ("pl", "pl_PL.UTF-8")):
        res, home = dry_run(ROOT / "install.sh", locale)
        assert res.returncode == 0, res.stderr
        for key in STEP_KEYS:
            assert translate(language, key) in res.stdout, (language, key)
        assert not any(home.rglob("*")), "dry run must not create files in HOME"


def test_uninstall_dry_run_changes_nothing() -> None:
    res, home = dry_run(ROOT / "uninstall.sh")
    assert res.returncode == 0, res.stderr
    assert not any(home.rglob("*"))


def test_installer_keys_exist_in_the_catalog() -> None:
    en = json.loads((ROOT / "eagleeye" / "locales" / "en.json").read_text(encoding="utf-8"))
    used = set(re.findall(r"installer\.[a-z_.]+[a-z_]", "".join(s.read_text(encoding="utf-8") for s in SCRIPTS)))
    assert used and not (used - set(en)), sorted(used - set(en))


def test_scripts_use_the_english_names() -> None:
    text = "".join(s.read_text(encoding="utf-8") for s in SCRIPTS)
    for old in ("zaslepka", "prywatnosc", "--wszystko", "zakoncz"):
        assert old not in text, old
    assert "eagleeye-placeholder.service" in text and "eagleeye-privacy" in text


if __name__ == "__main__":
    run(globals(), "Instalator")
