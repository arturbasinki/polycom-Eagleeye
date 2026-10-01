#!/usr/bin/env python3
"""Instalator: składnia, tryb --dry-run (nic nie zmienia), shellcheck, gdy jest.

    .venv/bin/python tests/test_install.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from runner import run  # noqa: E402

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


def dry_run(script: Path) -> tuple[subprocess.CompletedProcess, Path]:
    home = Path(tempfile.mkdtemp())
    # Backend pamięciowy: gsettings nie czyta prawdziwych ustawień i nie zakłada plików w HOME.
    env = dict(os.environ, HOME=str(home), XDG_DATA_HOME=str(home / ".local/share"),
               GSETTINGS_BACKEND="memory")
    res = subprocess.run(["bash", str(script), "--dry-run"], capture_output=True, text=True, env=env, timeout=60)
    return res, home


def test_install_dry_run_lists_every_step_and_changes_nothing() -> None:
    res, home = dry_run(ROOT / "install.sh")
    assert res.returncode == 0, res.stderr
    for header in ("Pakiety systemowe", "Moduł wirtualnej kamery", "Środowisko Pythona",
                   "Model pozy", "Wpis w menu", "Zaślepka wirtualnej kamery", "Skrót klawiszowy",
                   "Gotowe"):
        assert header in res.stdout, f"brak kroku: {header}"
    assert not any(home.rglob("*")), "dry-run utworzył pliki w HOME"


def test_uninstall_dry_run_changes_nothing() -> None:
    res, home = dry_run(ROOT / "uninstall.sh")
    assert res.returncode == 0, res.stderr
    assert not any(home.rglob("*"))


if __name__ == "__main__":
    run(globals(), "Instalator")
