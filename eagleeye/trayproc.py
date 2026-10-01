"""The tray icon as a child process of the engine (system python3 with GTK).

One retry after a crash; when there is no icon, the window closes the app instead of
hiding (otherwise the app would be invisible with no way back).
"""

from __future__ import annotations

import logging
import subprocess
import threading
from pathlib import Path

log = logging.getLogger("eagleeye")

SYSTEM_PYTHON = "/usr/bin/python3"
TRAY_SCRIPT = Path(__file__).resolve().parent.parent / "tray" / "eagleeye_tray.py"


class TrayProcess:
    def __init__(self, argv: list[str] | None = None, restarts: int = 1) -> None:
        self.argv = argv or [SYSTEM_PYTHON, str(TRAY_SCRIPT)]
        self._restarts_left = restarts
        self._proc: subprocess.Popen | None = None
        self._stopping = threading.Event()
        self.spawns = 0

    def _spawn(self) -> None:
        self._proc = subprocess.Popen(self.argv, stdin=subprocess.DEVNULL)
        self.spawns += 1

    def start(self) -> bool:
        try:
            self._spawn()
        except OSError as exc:
            log.warning("tray icon failed to start: %s", exc)
            return False
        threading.Thread(target=self._watch, name="tray-watch", daemon=True).start()
        return True

    def _watch(self) -> None:
        while not self._stopping.is_set():
            proc = self._proc
            if proc is None:
                return
            code = proc.wait()
            if self._stopping.is_set():
                return
            log.warning("tray icon exited (code %s)", code)
            if self._restarts_left <= 0:
                return
            self._restarts_left -= 1
            try:
                self._spawn()
            except OSError:
                return

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def stop(self) -> None:
        self._stopping.set()
        proc = self._proc
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                proc.kill()
