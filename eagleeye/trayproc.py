"""Ikona w zasobniku jako proces potomny silnika (systemowy python3 z GTK).

Jedna ponowna próba po awarii; gdy ikony nie ma, okno zamyka aplikację zamiast
się chować (inaczej aplikacja byłaby niewidoczna bez drogi powrotu).
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
            log.warning("ikona w zasobniku nie wystartowała: %s", exc)
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
            log.warning("ikona w zasobniku zakończyła się (kod %s)", code)
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
