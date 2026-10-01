#!/usr/bin/env python3
"""Gniazdo sterujące: polecenia, błędy, jedna instancja, martwe gniazdo.

    .venv/bin/python tests/test_control.py
"""

from __future__ import annotations

import os
import socket
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from runner import run  # noqa: E402

from eagleeye.control import (ControlServer, InstanceRunning, instance_running,  # noqa: E402
                              send, socket_path)


def temp_socket() -> Path:
    return Path(tempfile.mkdtemp()) / "eagleeye.sock"


def serve(handler):
    server = ControlServer(handler, temp_socket())
    server.start()
    return server


def test_command_reaches_handler_and_state_comes_back() -> None:
    got = []
    server = serve(lambda cmd, arg: got.append((cmd, arg)) or {"prywatnosc": True})
    try:
        reply = send("prywatnosc", "wl", server.path)
    finally:
        server.stop()
    assert got == [("prywatnosc", "wl")]
    assert reply == {"ok": True, "stan": {"prywatnosc": True}}


def test_handler_error_is_reported_and_server_survives() -> None:
    def handler(cmd, arg):
        if cmd == "zle":
            raise ValueError("nieznane polecenie")
        return {}
    server = serve(handler)
    try:
        bad = send("zle", None, server.path)
        good = send("stan", None, server.path)
    finally:
        server.stop()
    assert bad["ok"] is False and "nieznane polecenie" in bad["blad"]
    assert good["ok"] is True


def test_socket_is_private() -> None:
    server = serve(lambda cmd, arg: {})
    try:
        assert os.stat(server.path).st_mode & 0o077 == 0
    finally:
        server.stop()


def test_instance_running_and_stop_removes_socket() -> None:
    server = serve(lambda cmd, arg: {})
    path = server.path
    assert instance_running(path)
    server.stop()
    assert not path.exists() and not instance_running(path)


def test_stale_socket_is_removed() -> None:
    path = temp_socket()
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.bind(str(path))
    s.close()                                  # plik został, nikt nie słucha - jak po awarii
    assert path.exists()
    assert not instance_running(path)
    assert not path.exists()


def test_second_server_on_live_socket_refuses_to_start() -> None:
    first = serve(lambda cmd, arg: {"kto": "pierwszy"})
    second = ControlServer(lambda cmd, arg: {"kto": "drugi"}, first.path)
    try:
        try:
            second.start()
        except InstanceRunning:
            pass
        else:
            raise AssertionError("drugi serwer przejął gniazdo żywej instancji")
        assert send("stan", path=first.path)["stan"] == {"kto": "pierwszy"}
    finally:
        first.stop()


def test_server_starts_over_stale_socket() -> None:
    path = temp_socket()
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.bind(str(path))
    s.close()
    server = ControlServer(lambda cmd, arg: {"ok": 1}, path)
    server.start()
    try:
        assert send("stan", path=path)["stan"] == {"ok": 1}
    finally:
        server.stop()


def test_send_without_server_raises_oserror() -> None:
    try:
        send("stan", None, temp_socket())
    except OSError:
        return
    raise AssertionError("oczekiwano OSError")


def test_socket_path_uses_runtime_dir() -> None:
    old = os.environ.get("XDG_RUNTIME_DIR")
    os.environ["XDG_RUNTIME_DIR"] = "/tmp/xyz"
    try:
        assert socket_path() == Path("/tmp/xyz/eagleeye.sock")
    finally:
        if old is None:
            del os.environ["XDG_RUNTIME_DIR"]
        else:
            os.environ["XDG_RUNTIME_DIR"] = old


if __name__ == "__main__":
    run(globals(), "Gniazdo sterujące")
