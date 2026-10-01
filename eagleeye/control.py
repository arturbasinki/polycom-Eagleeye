"""Control a running app over a UNIX socket: one line of JSON each way.

Request ``{"cmd": ..., "arg": ...}``, reply ``{"ok": true, "state": {...}}`` or
``{"ok": false, "error": "...", "message": {...}}``. The module uses only the standard library -
the tray icon imports it too, running on the system python3 without the venv.

The socket also acts as a single-instance lock: whoever reaches it knows the app
is already running.
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

from .i18n import LocalizedError

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
            reply = {"ok": True, "state": state}
        except Exception as exc:     # one failing command must not kill the server
            reply = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            if isinstance(exc, LocalizedError):
                reply["message"] = exc.message.to_dict()
        self.wfile.write((json.dumps(reply, ensure_ascii=False) + "\n").encode())


class _Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True


class InstanceRunning(RuntimeError):
    """The socket belongs to a live instance - this process must not start."""


class ControlServer:
    def __init__(self, handler: Handler, path: Path | None = None) -> None:
        self.handler = handler
        self.path = Path(path or socket_path())
        self._server: _Server | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Takes the socket. InstanceRunning when a live instance answers on it.

        bind() is atomic: of two processes starting at once, one gets the socket and
        the other hits EADDRINUSE. The file left after a crash (nobody answers) is removed.
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
    """Sends a command. OSError when the app is not running."""
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
    """Whether another instance is running. A dead socket (after a crash) is removed."""
    p = Path(path or socket_path())
    try:
        send("state", path=p)
        return True
    except (OSError, ValueError):
        if p.exists():
            try:
                p.unlink()
            except OSError:
                pass
        return False
