"""Wątek auto-trackingu: klatka (z czasem V4L2) -> percepcja -> TrackingCore.

Cienka warstwa nad :class:`eagleeye.core.TrackingCore`. Odpowiada za:

* pobieranie klatek i dekodowanie w skali 1/2,
* bezpieczeństwo: brak klatek > 1 s zatrzymuje ruch; strażnik w wykonawcy
  zatrzymuje prędkość, gdyby ta pętla się zawiesiła,
* przejście detektora z GPU na CPU po 5 kolejnych błędach,
* sterowanie ręczne (tylko przy wyłączonym śledzeniu) - przez tego samego
  wykonawcę, żeby model głowicy wiedział o każdym ruchu,
* rejestrator sesji (JSONL) do odtwarzania w symulatorze,
* migawkę stanu dla interfejsu - niezmienny obiekt podmieniany w całości.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field, replace
from pathlib import Path

from .config import captures_dir
from .core import TrackingCore
from .detectors import Detection, decode_mjpeg_scaled
from .director import Command
from .framing import GOLDEN, SIDE_X, shot_for
from .head_model import Dynamics
from .i18n import Message
from .identity import AUTO, PersonTracker, TargetSelection, TrackInfo, track_at, track_infos
from .perception import Observation, default_perception
from .profiles import resolve
from .v4l2 import V4L2Error

log = logging.getLogger("eagleeye")

NO_FRAME_TIMEOUT = 1.0
# Stan wyboru osoby po wyczyszczeniu (wyłączone śledzenie, błąd numeracji).
IDENTITY_CLEARED = {"tracks": (), "selection": AUTO, "selected_id": None,
                    "selection_left": 0.0, "selection_note": None}
DETECTOR_FAILURES_TO_CPU = 5
ZOOM_REFRESH = 1.0


@dataclass
class TrackerSettings:
    profile: str = "talk"
    overrides: dict = field(default_factory=dict)
    use_gpu: bool = True
    invert_pan: bool = False
    invert_tilt: bool = False
    rate_hz: float = 15.0
    dynamics: Dynamics = field(default_factory=Dynamics)
    home: tuple[float, float] | None = None
    last_azimuth: tuple[float, float] | None = None
    record: bool = False
    auto_zoom: bool = True
    select_hold_s: float = 6.0


@dataclass(frozen=True)
class TrackerState:
    enabled: bool = False
    profile: str = ""
    mode: str = ""
    pan_state: str = ""
    tilt_state: str = ""
    note: Message | None = None
    message: str = "śledzenie wyłączone"
    detections: tuple[Detection, ...] = ()
    target: Observation | None = None
    frame_size: tuple[int, int] = (0, 0)
    pan: float = 0.0
    tilt: float = 0.0
    zones: tuple[float, float] = (0.0, 0.0)          # trigger_pan, trigger_tilt
    aim: tuple[float, float] = (0.5, GOLDEN)         # punkt docelowy głowy (ułamki kadru)
    side: str = ""                                   # strona kadru: środek / lewy / prawy
    shot: str = ""                                   # plan: CU / MCU / MS
    yaw: float | None = None                         # skręt twarzy celu
    zoom_goal: float | None = None                   # zoom wyliczony do planu
    auto_zoom: bool = False
    detection_ms: float = 0.0
    loop_ms: float = 0.0
    frame_age_ms: float = 0.0      # wiek klatki (od stempla bufora V4L2) w chwili jej pobrania
    fps: float = 0.0
    moves: int = 0
    detector: str = ""
    tracks: tuple[TrackInfo, ...] = ()               # osoby z numerami (widoczne i zawieszone)
    selection: str = AUTO                            # auto / selected / suspended
    selected_id: int | None = None
    selection_left: float = 0.0                      # s left to wait for a suspended person
    selection_note: Message | None = None            # e.g. the selected person vanished


class SessionRecorder:
    """Zapis sesji: pomiary głowy w kątach świata i rozkazy.

    Kąty świata nie zależą od ruchu kamery, więc sesję da się odtworzyć
    w symulatorze z innymi nastawami (tools/replay_session.py).
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._fh = open(path, "w", encoding="utf-8")

    @classmethod
    def create(cls, directory: Path | None = None) -> SessionRecorder:
        directory = directory or (captures_dir() / "sessions")
        directory.mkdir(parents=True, exist_ok=True)
        return cls(directory / (time.strftime("%Y%m%d-%H%M%S") + ".jsonl"))

    def write(self, t: float, world: tuple[float, float] | None, cmds: list[Command], mode: str,
              framing: dict | None = None) -> None:
        row = {"t": round(t, 4),
               "world": None if world is None else [round(world[0], 1), round(world[1], 1)],
               "cmds": [[c.kind, c.axis, c.value] for c in cmds],
               "mode": mode}
        if framing:
            row.update(framing)
        self._fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    def close(self) -> None:
        self._fh.close()


def load_session(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


class Tracker:
    def __init__(self, stream, controls, settings: TrackerSettings,
                 perception_factory=default_perception) -> None:
        self.stream = stream
        self.controls = controls
        self.settings = settings
        self._factory = perception_factory
        self.core = TrackingCore(controls, resolve(settings.profile, settings.overrides), settings.dynamics,
                                 invert_pan=settings.invert_pan, invert_tilt=settings.invert_tilt)
        self.core.director.home = settings.home
        self.core.director.last_azimuth = settings.last_azimuth
        self.core.director.auto_zoom = settings.auto_zoom
        self.core.director.reset()
        self._perception = None
        self._lock = threading.RLock()
        self._state = TrackerState(auto_zoom=settings.auto_zoom)
        self._enabled = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._det_errors = 0
        self._moves = 0
        self._recorder: SessionRecorder | None = None
        self._extra_note = ""
        self._people = PersonTracker()
        self._selection = TargetSelection(settings.select_hold_s)
        self._sel_lock = threading.Lock()       # osobno od _lock: wybór klika wątek UI, liczy wątek pętli
        self._identity_view: dict = {}
        self.core.actuator.sync_from_device(time.monotonic())

    # --- cykl życia ------------------------------------------------------

    def start(self) -> None:
        self.core.actuator.start_watchdog()
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="tracker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        with self._lock:
            try:
                self.core.actuator.stop_all(time.monotonic())
            except V4L2Error:
                pass
            self.core.actuator.stop_watchdog()
            self._close_recorder()

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, on: bool) -> None:
        with self._lock:
            t = time.monotonic()
            if on and not self._enabled:
                self.core.actuator.refresh_zoom()       # zoom mógł zmienić suwak albo preset
                self.core.filter.reset()
                self._reset_identity()
                self.core.director.start_search(t, self.core.actuator.zoom_value)
                if self.settings.record:
                    self._recorder = SessionRecorder.create()
            elif not on and self._enabled:
                self.core.actuator.stop_all(t)
                self.core.director.reset()
                self._reset_identity()
                self._close_recorder()
            self._enabled = on
        self._publish(enabled=on, message="śledzenie włączone" if on else "śledzenie wyłączone")

    def set_record(self, on: bool, directory: Path | None = None) -> None:
        """Włącza/wyłącza zapis sesji od razu - także w trakcie śledzenia."""
        with self._lock:
            self.settings.record = bool(on)
            if on and self._enabled and self._recorder is None:
                self._recorder = SessionRecorder.create(directory)
                log.info("zapis sesji: %s", self._recorder.path)
            elif not on:
                self._close_recorder()

    def _close_recorder(self) -> None:
        if self._recorder is not None:
            self._recorder.close()
            log.info("zapis sesji: %s", self._recorder.path)
            self._recorder = None

    # --- polecenia z interfejsu --------------------------------------------

    def select_at(self, x: float, y: float) -> bool:
        """Wybiera do śledzenia osobę widoczną w punkcie klatki (piksele ``state.frame_size``).
        ``False``, gdy nikogo tam nie ma - wtedy wybór się nie zmienia."""
        with self._sel_lock:
            tid = track_at(self._state.tracks, x, y)
            if tid is None:
                return False
            self._selection.select(tid, time.monotonic())
            return True

    def clear_selection(self) -> None:
        """Wraca do trybu automatycznego (największa osoba)."""
        with self._sel_lock:
            self._selection.clear()

    def set_select_hold(self, seconds: float) -> None:
        """Ile sekund kamera czeka na wybraną osobę, która zniknęła, zanim wróci do trybu automatycznego."""
        with self._sel_lock:
            self.settings.select_hold_s = float(seconds)
            self._selection.hold_s = float(seconds)

    def _reset_identity(self) -> None:
        with self._sel_lock:
            self._people.reset()
            self._selection.clear()
        self._identity_view = {}
        self._publish(**IDENTITY_CLEARED)

    def search_now(self) -> None:
        with self._lock:
            self.core.filter.reset()
            self.core.director.start_search(time.monotonic(), self.core.actuator.zoom_value)

    def set_profile(self, name: str, overrides: dict | None = None) -> None:
        with self._lock:
            self.settings.profile = name
            self.settings.overrides = dict(overrides or {})
            self.core.director.set_profile(resolve(name, self.settings.overrides))

    def set_home(self) -> tuple[float, float]:
        with self._lock:
            home = self.core.head.angles(time.monotonic())
            self.core.director.home = home
            self.settings.home = home
            return home

    def position(self) -> tuple[float, float]:
        """Gdzie według modelu głowicy patrzy teraz kamera (pan, tilt)."""
        with self._lock:
            return self.core.head.angles(time.monotonic())

    def tilt_min(self) -> float:
        """Dolna granica tiltu z kontrolki kamery - obiektyw maksymalnie w dół."""
        return self.core.director.limits.tilt_min

    def move_to(self, pan: float | None = None, tilt: float | None = None) -> bool:
        """Ruch ręczny. Odrzucony (False), gdy działa śledzenie."""
        with self._lock:
            if self._enabled:
                return False
            t = time.monotonic()
            if pan is not None:
                self.core.actuator.move_absolute("pan", pan, t)
            if tilt is not None:
                self.core.actuator.move_absolute("tilt", tilt, t)
            return True

    def nudge(self, d_pan: float, d_tilt: float) -> bool:
        with self._lock:
            t = time.monotonic()
            pan, tilt = self.core.head.angles(t)
            return self.move_to(pan + d_pan if d_pan else None, tilt + d_tilt if d_tilt else None)

    def set_use_gpu(self, flag: bool) -> None:
        with self._lock:
            self.settings.use_gpu = bool(flag)
            self._perception = None

    def set_auto_zoom(self, on: bool) -> None:
        with self._lock:
            self.settings.auto_zoom = bool(on)
            self.core.director.auto_zoom = bool(on)
            if on:
                self.core.actuator.refresh_zoom()   # zoom mógł zmienić suwak albo preset
            self._publish(auto_zoom=bool(on))

    @property
    def last_azimuth(self) -> tuple[float, float] | None:
        return self.core.director.last_azimuth

    @property
    def state(self) -> TrackerState:
        return self._state

    # --- pętla -----------------------------------------------------------

    def _publish(self, **changes) -> None:
        self._state = replace(self._state, **changes)

    def _framing_row(self) -> dict:
        """Pola kadru do zapisu sesji (odtwarzacz symulatora, tools/framing_stats.py)."""
        est = self.core.last_estimate
        return {"yaw": None if est is None or est.yaw is None else round(est.yaw, 3),
                "head_scale": None if est is None or est.head_scale is None else round(est.head_scale, 1),
                "side": self.core.director.side.side,
                "zoom_goal": self.core.director.last_zoom_goal,
                "zoom": self.core.actuator.zoom_value,
                "auto_zoom": self.core.director.auto_zoom}

    def _previous_point(self, w: int, h: int) -> tuple[float, float] | None:
        now = time.monotonic()
        est = self.core.filter.estimate(now)
        if est is None:
            return None
        return self.core.view(w, h).world_to_pixel(est.pan, est.tilt, *self.core.head.angles(now))

    def _apply_identity(self, frame, ts: float, dets, obs, w: int, h: int):
        """Numeruje osoby (eagleeye.identity) i, gdy użytkownik kogoś wybrał, podmienia cel na
        jego wykrycie albo na ``None`` (zawieszona: kamera stoi, nie przechodzi na innego)."""
        if self.core.actuator.zoom_model.moving(ts):
            # Jak w core.step: w trakcie jazdy zoomu pole widzenia z kontrolki nie jest prawdziwe,
            # a błąd skaluje położenia i rozmiary - numeracji nie ruszamy, a przy wybranej osobie
            # kamera i tak nie dostaje pomiaru (nigdy nie oddajemy celu innej osobie).
            with self._sel_lock:
                return None if self._selection.state != AUTO else obs
        try:
            view = self.core.view(w, h)
            cam_pan, cam_tilt = self.core.head.angles(ts)

            def to_world(x: float, y: float) -> tuple[float, float]:
                return view.pixel_to_world(x, y, cam_pan, cam_tilt)

            with self._sel_lock:
                sel = self._selection
                keep = None if sel.state == AUTO else sel.track_id
                tracks = self._people.update(dets, frame, ts, to_world, protect=keep,
                                             protect_s=sel.hold_s)
                picked = sel.resolve(tracks, ts)
                if sel.state != AUTO:
                    obs = None if picked is None else self._perception.observation(picked.det, ts)
                self._identity_view = {
                    "tracks": track_infos(tracks), "selection": sel.state,
                    "selected_id": sel.track_id, "selection_left": sel.remaining(ts),
                    "selection_note": sel.event}
        except Exception:
            # Błąd numeracji nie może zablokować kamery na "duchu": wracamy do trybu automatycznego.
            log.exception("błąd numeracji osób - wybór wyczyszczony")
            with self._sel_lock:
                self._people.reset()
                self._selection.clear()
            self._identity_view = {**IDENTITY_CLEARED, "selection_note": "błąd numeracji osób"}
        return obs

    def _perceive(self, frame, ts: float):
        try:
            if self._perception is None:
                self._perception = self._factory(self.settings.use_gpu)
            h, w = frame.shape[:2]
            obs, dets = self._perception.observe(frame, ts, self._previous_point(w, h))
            obs = self._apply_identity(frame, ts, dets, obs, w, h)
            self._det_errors = 0
            return obs, dets, self._perception.last_ms
        except Exception as exc:
            self._det_errors += 1
            log.warning("błąd detektora (%d z rzędu): %s", self._det_errors, exc)
            if self._det_errors >= DETECTOR_FAILURES_TO_CPU and self.settings.use_gpu:
                self.settings.use_gpu = False
                self._perception = None
                self._det_errors = 0
                self._extra_note = "detektor GPU zawodzi - przełączono na CPU"
            return None, [], 0.0

    def _loop(self) -> None:
        last_id = 0
        last_frame_at = time.monotonic()
        zoom_checked = 0.0
        fps = 0.0
        prev = time.perf_counter()
        while not self._stop.is_set():
            started = time.perf_counter()
            interval = 1.0 / max(1.0, self.settings.rate_hz)
            fid, jpg, ts = self.stream.frame_timed(last_id, timeout=0.5)
            now = time.monotonic()
            if jpg is None or fid == last_id:
                if self._enabled and now - last_frame_at > NO_FRAME_TIMEOUT:
                    with self._lock:
                        try:
                            self.core.actuator.stop_all(now)
                        except V4L2Error:
                            pass
                    self._publish(message="brak obrazu z kamery - ruch wstrzymany")
                continue
            last_id, last_frame_at = fid, now
            frame_age_ms = (now - ts) * 1000.0 if ts else 0.0
            if not self._enabled:
                self._publish(detections=(), target=None, tracks=())
                time.sleep(0.05)
                continue
            frame = decode_mjpeg_scaled(jpg, 2)
            if frame is None:
                continue
            h, w = frame.shape[:2]
            obs, dets, det_ms = self._perceive(frame, ts)
            try:
                with self._lock:
                    if now - zoom_checked > ZOOM_REFRESH:
                        zoom_checked = now
                        # Ręcznie zmieniony zoom (pierścień, suwak) trwale wyłącza zoom
                        # automatyczny - model głowicy i tak wie, gdzie jest optyka.
                        if self.core.actuator.refresh_zoom(now) and self.core.director.auto_zoom:
                            self.core.director.auto_zoom = False
                            self.settings.auto_zoom = False
                            log.info("zoom zmieniony ręcznie - zoom automatyczny wyłączony")
                    cmds = self.core.step(time.monotonic(), obs, w, h)
                    if self._recorder is not None:
                        self._recorder.write(now, self.core.last_world, cmds,
                                              self.core.director.status.mode, self._framing_row())
            except V4L2Error as exc:
                self._enabled = False
                self._publish(enabled=False, message=f"kamera odłączona: {exc}")
                continue
            except Exception as exc:
                # Błąd w logice śledzenia nie może po cichu zabić wątku: interfejs
                # pokazywałby "śledzenie", a nic by się nie działo. Zatrzymujemy ruch,
                # wyłączamy śledzenie i zostawiamy wątek - da się włączyć ponownie.
                log.exception("błąd śledzenia")
                with self._lock:
                    self._enabled = False
                    try:
                        self.core.actuator.stop_all(time.monotonic())
                    except V4L2Error:
                        pass
                    self.core.director.reset()
                    self._close_recorder()
                self._publish(enabled=False, message=f"błąd śledzenia - wyłączone: {exc}")
                continue
            self._moves += sum(1 for c in cmds if c.kind == "abs")
            tick = time.perf_counter()
            fps = 0.8 * fps + 0.2 / max(1e-3, tick - prev) if fps else 1.0 / max(1e-3, tick - prev)
            prev = tick
            status = self.core.director.status
            profile = self.core.director.profile
            est = self.core.last_estimate
            pan, tilt = self.core.head.angles(time.monotonic())
            self._publish(
                enabled=True, profile=profile.name, mode=status.mode, pan_state=status.pan,
                tilt_state=status.tilt, note=status.note,
                message=self._extra_note or status.note or status.mode,
                detections=tuple(dets), target=obs, frame_size=(w, h), pan=pan, tilt=tilt,
                zones=(profile.trigger_pan, profile.trigger_tilt),
                aim=(SIDE_X[self.core.director.side.side], GOLDEN),
                side=self.core.director.side.side,
                shot=shot_for(profile).name,
                yaw=None if est is None else est.yaw,
                zoom_goal=self.core.director.last_zoom_goal,
                auto_zoom=self.core.director.auto_zoom,
                detection_ms=det_ms, loop_ms=(time.perf_counter() - started) * 1000.0,
                frame_age_ms=frame_age_ms,
                fps=fps, moves=self._moves,
                detector=self._perception.description if self._perception else "",
                **self._identity_view
            )
            rest = interval - (time.perf_counter() - started)
            if rest > 0:
                time.sleep(rest)
