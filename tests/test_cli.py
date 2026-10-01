#!/usr/bin/env python3
"""The eagleeye command: controlling a running app and a single instance.

    .venv/bin/python tests/test_cli.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from runner import run  # noqa: E402

import eagleeye.cli as cli  # noqa: E402
from eagleeye.control import ControlServer  # noqa: E402
from eagleeye.i18n import t  # noqa: E402


def with_runtime_dir():
    d = tempfile.mkdtemp()
    os.environ["XDG_RUNTIME_DIR"] = d
    return Path(d) / "eagleeye.sock"


def test_command_without_running_app_fails_with_notification() -> None:
    with_runtime_dir()
    notes = []
    cli.notify = notes.append
    assert cli.main(["privacy"]) == 1
    assert notes and notes[0] == t("cli.not_running_notify")


def test_command_reaches_running_app() -> None:
    path = with_runtime_dir()
    got = []
    server = ControlServer(lambda cmd, arg: got.append((cmd, arg)) or {}, path)
    server.start()
    try:
        assert cli.main(["tracking", "on"]) == 0
    finally:
        server.stop()
    assert got == [("tracking", "on")]


def test_second_start_only_shows_existing_window() -> None:
    path = with_runtime_dir()
    got = []
    server = ControlServer(lambda cmd, arg: got.append(cmd) or {}, path)
    server.start()
    try:
        assert cli.main([]) == 0
    finally:
        server.stop()
    assert got == ["state", "show"], got


def test_autozoom_is_a_known_command() -> None:
    assert "autozoom" in cli.COMMANDS


def test_select_is_a_known_command() -> None:
    assert "select" in cli.COMMANDS and "select" in cli.__doc__


def test_failed_command_returns_1_and_notifies() -> None:
    path = with_runtime_dir()
    notes = []
    cli.notify = notes.append

    def handler(cmd, arg):
        raise RuntimeError("turn privacy off first")
    server = ControlServer(handler, path)
    server.start()
    try:
        assert cli.main(["tracking", "on"]) == 1
    finally:
        server.stop()
    assert notes and "privacy" in notes[0]


if __name__ == "__main__":
    run(globals(), "The eagleeye command")
