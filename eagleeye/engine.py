"""Silnik aplikacji: kamera, śledzenie, wirtualna kamera i prywatność - niezależnie od okna.

Okno Flet, ikona w zasobniku i polecenia ``eagleeye ...`` są tylko widokami
i pilotami tego obiektu. Silnik żyje przez cały czas działania procesu, także
gdy okno jest schowane.
"""

from __future__ import annotations

import _thread
import errno
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from .config import Store
from .head_model import dynamics_from_settings
from .privacy import Privacy
from .profiles import PROFILES
from .tracker import Tracker, TrackerSettings
from .v4l2 import ControlDevice, MjpegStream, V4L2Error
from .vcam import VirtualCamera

log = logging.getLogger("eagleeye")

PARK_TOLERANCE = 1800      # jednostki kontrolek pan/tilt (1/3600°): pół stopnia

_ON = {"wl", "wł", "on", "1"}
_OFF = {"wyl", "wył", "off", "0"}


def _switch(arg: str | None, current: bool) -> bool:
    if arg is None or arg in ("przelacz", "przełącz"):
        return not current
    if arg in _ON:
        return True
    if arg in _OFF:
        return False
    raise ValueError(f"nieznany argument {arg!r} (wl / wyl / przelacz)")


def device_holders(device: str) -> list[str]:
    """Nazwy procesów (poza nami), które mają otwarte ``device`` - z /proc/*/fd."""
    target = os.path.realpath(device)
    names = []
    for pid in filter(str.isdigit, os.listdir("/proc")):
        if int(pid) == os.getpid():
            continue
        try:
            fds = os.listdir(f"/proc/{pid}/fd")
            if any(os.path.realpath(f"/proc/{pid}/fd/{fd}") == target for fd in fds):
                with open(f"/proc/{pid}/comm", encoding="utf-8") as f:
                    names.append(f.read().strip())
        except OSError:
            continue                              # proces zniknął albo nie nasz
    return sorted(set(names))


def _noop() -> None:
    pass


@dataclass
class UiHooks:
    """Co okno potrafi zrobić na polecenie z zewnątrz. Domyślnie - bez okna:
    ``quit`` przerywa główny wątek (KeyboardInterrupt), żeby proces się zamknął."""

    show: Callable[[], None] = _noop
    hide: Callable[[], None] = _noop
    quit: Callable[[], None] = field(default=_thread.interrupt_main)


class Engine:
    def __init__(self, store: Store, stream_factory=MjpegStream, controls_factory=ControlDevice,
                 tracker_factory=Tracker, vcam: VirtualCamera | None = None,
                 busy_retry_s: float = 3.0,
                 holders: Callable[[str], list[str]] = device_holders) -> None:
        self.store = store
        self.settings = store.settings
        self._stream_factory = stream_factory
        self._controls_factory = controls_factory
        self._tracker_factory = tracker_factory
        self.stream = None
        self.controls = None
        self.tracker: Tracker | None = None
        self.caps: dict | None = None
        self.error: str | None = None
        self.vcam = vcam if vcam is not None else VirtualCamera()
        self.privacy = Privacy(self.vcam)
        self.ui = UiHooks()
        self._lock = threading.RLock()
        self._busy_retry_s = busy_retry_s
        self._holders = holders
        self._busy = False                 # kamera zajęta przez inny program - ponawiamy sami
        self._stop = threading.Event()
        self._retry_thread: threading.Thread | None = None

    # --- cykl życia --------------------------------------------------------

    def start(self) -> None:
        self.vcam.start()
        self.open_camera()
        self._stop.clear()
        self._retry_thread = threading.Thread(target=self._retry_loop, name="camera-retry", daemon=True)
        self._retry_thread.start()

    def _retry_loop(self) -> None:
        """Gdy kamerę trzyma inny program (np. Meet wybrał kamerę fizyczną zamiast
        „EagleEye”), ponawiamy otwarcie - po przełączeniu w Meet śledzenie wraca samo."""
        while not self._stop.wait(self._busy_retry_s):
            if self._busy and self.tracker is None:
                self.open_camera()

    def shutdown(self, park_wait: float = 3.0) -> None:
        """Pełne zamknięcie. Przy włączonej prywatności najpierw przywraca pozycję
        głowicy (inaczej po następnym starcie obiektyw patrzyłby w podłogę) i czeka
        do ``park_wait`` s, aż model głowicy powie, że dojechała."""
        self._stop.set()
        if self._retry_thread is not None:
            self._retry_thread.join(timeout=2.0)
            self._retry_thread = None
        with self._lock:
            tracker = self.tracker
            if self.privacy.active and tracker is not None:
                target = self.privacy.saved_pose
                self.privacy.disable(tracker, resume_tracking=False)
                if target is not None:
                    deadline = time.monotonic() + park_wait
                    while time.monotonic() < deadline and max(
                            abs(a - b) for a, b in zip(tracker.position(), target)) > PARK_TOLERANCE:
                        time.sleep(0.05)
            self.close_camera()
            self.vcam.stop()

    def tracker_settings(self) -> TrackerSettings:
        tr = self.settings["tracking"]
        return TrackerSettings(
            profile=tr["profile"], overrides=dict(tr["overrides"]), use_gpu=bool(tr["use_gpu"]),
            invert_pan=bool(tr["invert_pan"]), invert_tilt=bool(tr["invert_tilt"]),
            rate_hz=float(tr["rate_hz"]), dynamics=dynamics_from_settings(self.settings["dynamics"]),
            home=tuple(tr["home"]) if tr["home"] else None,
            last_azimuth=tuple(tr["last_azimuth"]) if tr["last_azimuth"] else None,
            record=bool(tr["record"]),
            auto_zoom=bool(tr["auto_zoom"]),
            select_hold_s=float(tr["select_hold_s"]),
        )

    def open_camera(self) -> str | None:
        """(Ponownie) otwiera kamerę. Zwraca komunikat błędu albo None."""
        with self._lock:
            self.close_camera()
            device = self.settings["device"]
            try:
                self.controls = self._controls_factory(device)
                self.caps = self.controls.capabilities()
            except (OSError, V4L2Error) as exc:
                self.controls = None
                return self._fail(f"nie mogę otworzyć {device}: {exc}")
            if not self.caps["is_capture"]:
                self.close_camera()
                return self._fail(f"{device} to nie jest węzeł przechwytujący (karta: {self.caps['card']!r})")
            try:
                self.stream = self._stream_factory(device, self.settings["preview_width"],
                                                    self.settings["preview_height"])
                self.stream.start()
            except (OSError, V4L2Error) as exc:
                self.close_camera()
                if isinstance(exc, OSError) and exc.errno == errno.EBUSY:
                    return self._fail_busy(device)
                return self._fail(f"strumień nie wstał: {exc}")
            self.tracker = self._tracker_factory(self.stream, self.controls, self.tracker_settings())
            self.tracker.start()
            self.vcam.set_source(self.stream)
            self.error, self._busy = None, False
            log.info("kamera podłączona: %s (%s)", self.caps["card"], self.caps["bus_info"])
            return None

    def _fail(self, message: str) -> str:
        self.error, self._busy = message, False
        log.error("%s", message)
        return message

    def _fail_busy(self, device: str) -> str:
        who = ", ".join(self._holders(device)) or "inny program"
        message = (f"kamerę {device} zajmuje: {who} - w Meet / Teams / OBS wybierz kamerę "
                   f"„EagleEye”, nie „Polycom…”; połączę się sam, gdy się zwolni")
        if message != self.error:
            log.warning("%s", message)
        self.error, self._busy = message, True
        return message

    def close_camera(self) -> None:
        """Zatrzymuje tracker przed zamknięciem kontrolek - zeruje prędkości na SWOICH kontrolkach."""
        with self._lock:
            self.vcam.set_source(None)
            if self.tracker is not None:
                self.tracker.stop()
                self.tracker = None
            if self.stream is not None:
                try:
                    self.stream.stop()
                except Exception:
                    pass
                self.stream = None
            if self.controls is not None:
                self.controls.close()
                self.controls = None

    # --- polecenia -----------------------------------------------------------

    def set_privacy(self, on: bool) -> None:
        with self._lock:
            if on:
                self.privacy.enable(self.tracker)
            else:
                self.privacy.disable(self.tracker)

    def set_tracking(self, on: bool) -> None:
        with self._lock:
            if self.tracker is None:
                raise RuntimeError("kamera niepodłączona")
            if on and self.privacy.active:
                raise RuntimeError("najpierw wyłącz prywatność")
            self.tracker.set_enabled(on)

    def command(self, cmd: str, arg: str | None = None) -> dict:
        if cmd == "pokaz":
            self.ui.show()
        elif cmd == "schowaj":
            self.ui.hide()
        elif cmd == "prywatnosc":
            self.set_privacy(_switch(arg, self.privacy.active))
        elif cmd == "sledzenie":
            self.set_tracking(_switch(arg, bool(self.tracker and self.tracker.enabled)))
        elif cmd == "profil":
            if arg not in PROFILES:
                raise ValueError(f"nieznany profil {arg!r} ({', '.join(PROFILES)})")
            tr = self.settings["tracking"]
            tr["profile"], tr["overrides"] = arg, {}
            if self.tracker is not None:
                self.tracker.set_profile(arg, {})
            self.store.save()
        elif cmd == "autozoom":
            tr = self.settings["tracking"]
            tr["auto_zoom"] = _switch(arg, self._auto_zoom())
            if self.tracker is not None:
                self.tracker.set_auto_zoom(tr["auto_zoom"])
            self.store.save()
        elif cmd == "wybierz":
            self._select(arg)
        elif cmd == "zakoncz":
            self.ui.quit()
        elif cmd != "stan":
            raise ValueError(f"nieznane polecenie {cmd!r}")
        return self.state()

    def _select(self, arg: str | None) -> None:
        """``wybierz x,y`` - osoba pod punktem klatki (układ ``stan.wybor.klatka``);
        ``wybierz brak`` - z powrotem tryb automatyczny."""
        with self._lock:
            if self.tracker is None:
                raise RuntimeError("kamera niepodłączona")
            if arg == "brak":
                self.tracker.clear_selection()
                return
            try:
                x, y = (float(v) for v in (arg or "").split(","))
            except ValueError:
                raise ValueError(f"wybierz oczekuje x,y albo 'brak' (dostałem {arg!r})") from None
            self.tracker.select_at(x, y)

    def state(self) -> dict:
        tracker = self.tracker
        return {
            "kamera": tracker is not None,
            "blad": self.error,
            "sledzenie": bool(tracker and tracker.enabled),
            "profil": self.settings["tracking"]["profile"],
            "prywatnosc": self.privacy.active,
            "zoom_auto": self._auto_zoom(),
            "kadr": self._framing(tracker),
            "wybor": self._selection(tracker),
            "wirtualna_kamera": self.vcam.status,
            "wydajnosc": self._performance(tracker),
        }

    def _auto_zoom(self) -> bool:
        if self.tracker is not None:
            return bool(self.tracker.settings.auto_zoom)
        return bool(self.settings["tracking"]["auto_zoom"])

    @staticmethod
    def _framing(tracker) -> dict | None:
        """Kadr (strona, plan, yaw, zoom docelowy) albo None, gdy brak kamery."""
        if tracker is None:
            return None
        st = tracker.state
        return {"strona": st.side, "plan": st.shot, "yaw": st.yaw, "zoom_cel": st.zoom_goal}

    @staticmethod
    def _selection(tracker) -> dict | None:
        """Wybór osoby: stan, numer, osoby w kadrze i rozmiar klatki, w którym liczy się ``wybierz x,y``."""
        if tracker is None:
            return None
        st = tracker.state
        return {"stan": st.selection, "id": st.selected_id, "zostalo_s": round(st.selection_left, 1),
                "uwaga": st.selection_note, "klatka": list(st.frame_size),
                "osoby": [{"id": i.id, "ramka": list(i.box), "widoczna": i.visible} for i in st.tracks]}

    @staticmethod
    def _performance(tracker) -> dict | None:
        """Liczby do diagnozy płynności śledzenia (widać je też w oknie)."""
        if tracker is None:
            return None
        st = tracker.state
        return {"hz": round(st.fps, 1), "detekcja_ms": round(st.detection_ms, 1),
                "petla_ms": round(st.loop_ms, 1), "wiek_klatki_ms": round(st.frame_age_ms, 1),
                "ruchy": st.moves, "tryb": st.mode}
