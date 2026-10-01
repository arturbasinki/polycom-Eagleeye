"""Sterowanie działającą aplikacją przez gniazdo UNIX: jedna linia JSON w każdą stronę.

Żądanie ``{"cmd": ..., "arg": ...}``, odpowiedź ``{"ok": true, "stan": {...}}`` albo
``{"ok": false, "blad": "..."}``. Moduł używa wyłącznie biblioteki standardowej -
importuje go też ikona w zasobniku, działająca na systemowym python3 bez venv.

Gniazdo służy też jako blokada jednej instancji: kto się do niego dodzwoni,
ten wie, że aplikacja już działa.
"""

from __future__ import annotations

import errno
import json
import os
import socket
import socketserver
import tempfile
import threading
from pathlib import Path
from typing import Callable

SOCKET_NAME = "eagleeye.sock"
TIMEOUT_S = 2.0

Handler = Callable[[str, "str | None"], dict]


def socket_path() -> Path:
    return Path(os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()) / SOCKET_NAME


class _Request(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        line = self.rfile.readline(65536)
        try:
            msg = json.loads(line)
            state = self.server.handler(str(msg["cmd"]), msg.get("arg"))
            reply = {"ok": True, "stan": state}
        except Exception as exc:     # błąd jednego polecenia nie może zabić serwera
            reply = {"ok": False, "blad": f"{type(exc).__name__}: {exc}"}
        self.wfile.write((json.dumps(reply, ensure_ascii=False) + "\n").encode())


class _Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True


class InstanceRunning(RuntimeError):
    """Gniazdo należy do żywej instancji - ten proces ma się nie uruchamiać."""


class ControlServer:
    def __init__(self, handler: Handler, path: Path | None = None) -> None:
        self.handler = handler
        self.path = Path(path or socket_path())
        self._server: _Server | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Zajmuje gniazdo. InstanceRunning, gdy odpowiada na nim żywa instancja.

        bind() jest atomowy: z dwóch procesów startujących naraz gniazdo dostaje
        jeden, drugi trafia na EADDRINUSE. Plik po awarii (nikt nie odpowiada) usuwamy.
        """
        old_umask = os.umask(0o177)
        try:
            try:
                self._server = _Server(str(self.path), _Request)
            except OSError as exc:
                if exc.errno != errno.EADDRINUSE:
                    raise
                if instance_running(self.path):      # martwe gniazdo usuwa samo
                    raise InstanceRunning(str(self.path)) from exc
                self._server = _Server(str(self.path), _Request)
        finally:
            os.umask(old_umask)
        self._server.handler = self.handler
        self._thread = threading.Thread(target=self._server.serve_forever, name="control", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


def send(cmd: str, arg: str | None = None, path: Path | None = None, timeout: float = TIMEOUT_S) -> dict:
    """Wysyła polecenie. OSError, gdy aplikacja nie działa."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        s.connect(str(path or socket_path()))
        s.sendall((json.dumps({"cmd": cmd, "arg": arg}) + "\n").encode())
        data = b""
        while not data.endswith(b"\n"):
            chunk = s.recv(65536)
            if not chunk:
                break
            data += chunk
    return json.loads(data)


def instance_running(path: Path | None = None) -> bool:
    """Czy działa inna instancja. Martwe gniazdo (po awarii) jest usuwane."""
    p = Path(path or socket_path())
    try:
        send("stan", path=p)
        return True
    except (OSError, ValueError):
        if p.exists():
            try:
                p.unlink()
            except OSError:
                pass
        return False
