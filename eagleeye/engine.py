"""Application engine: camera, tracking, virtual camera and privacy - independent of the window.

The Flet window, the tray icon and the ``eagleeye ...`` commands are only views
and remotes for this object. The engine lives for the whole life of the process, also
when the window is hidden.
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

import numpy as np

from .config import Store
from .detectors import decode_mjpeg
from .head_model import dynamics_from_settings
from .i18n import AUTO, LocalizedError, Message, available_languages, get_language, msg, set_language
from .identity import AUTO as SELECTION_AUTO
from .lightfix import FAILED, NO_FRAME, OK, WELL_LIT, LightResult, analyse
from .privacy import Privacy
from .profiles import DEFAULT_PROFILE, PROFILES
from .tracker import Tracker, TrackerSettings
from .v4l2 import ControlDevice, MjpegStream, V4L2Error
from .vcam import VirtualCamera

log = logging.getLogger("eagleeye")

PARK_TOLERANCE = 1800      # pan/tilt control units (1/3600°): half a degree

_ON = {"on", "1"}
_OFF = {"off", "0"}


def _switch(arg: str | None, current: bool) -> bool:
    if arg is None or arg == "toggle":
        return not current
    if arg in _ON:
        return True
    if arg in _OFF:
        return False
    raise ValueError(f"unknown argument {arg!r} (on / off / toggle)")


def device_holders(device: str) -> list[str]:
    """Process names (other than us) that have ``device`` open - from /proc/*/fd."""
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
            continue                              # the process vanished or is not ours
    return sorted(set(names))


def _noop() -> None:
    pass


@dataclass
class UiHooks:
    """What the window can do on an external command. Default - no window:
    ``quit`` interrupts the main thread (KeyboardInterrupt) so the process closes."""

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
        set_language(self.settings["language"])
        tracking = self.settings["tracking"]
        if tracking["profile"] not in PROFILES:      # e.g. a value saved by an older version
            tracking["profile"] = DEFAULT_PROFILE
        self._stream_factory = stream_factory
        self._controls_factory = controls_factory
        self._tracker_factory = tracker_factory
        self.stream = None
        self.controls = None
        self.tracker: Tracker | None = None
        self.caps: dict | None = None
        self.error: Message | None = None
        self.vcam = vcam if vcam is not None else VirtualCamera()
        self.privacy = Privacy(self.vcam)
        self.ui = UiHooks()
        self._light_lut: np.ndarray | None = None      # light-correction table; memory only, gone after a restart
        self._light_generation = 0                     # bumped by reset_light; drops a table computed before it
        self._lock = threading.RLock()
        self._busy_retry_s = busy_retry_s
        self._holders = holders
        self._busy = False                 # camera busy in another program - we retry ourselves
        self._stop = threading.Event()
        self._retry_thread: threading.Thread | None = None

    # --- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        self.vcam.start()
        self.open_camera()
        self._stop.clear()
        self._retry_thread = threading.Thread(target=self._retry_loop, name="camera-retry", daemon=True)
        self._retry_thread.start()

    def _retry_loop(self) -> None:
        """When another program holds the camera (e.g. Meet picked the physical camera instead
        of "EagleEye"), we retry opening - after switching in Meet, tracking comes back by itself."""
        while not self._stop.wait(self._busy_retry_s):
            if self._busy and self.tracker is None:
                self.open_camera()

    def shutdown(self, park_wait: float = 3.0) -> None:
        """Full shutdown. With privacy on, first restores the head position
        (otherwise after the next start the lens would point at the floor) and waits
        up to ``park_wait`` s for the head model to say it has arrived."""
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

    def open_camera(self) -> Message | None:
        """(Re)opens the camera. Returns an error message or None. Tracking that was on stays on:
        the new tracker starts switched off, so a "Resolution" change used to turn it off."""
        with self._lock:
            was_tracking = self.tracker is not None and self.tracker.enabled
            self.close_camera()
            device = self.settings["device"]
            try:
                self.controls = self._controls_factory(device)
                self.caps = self.controls.capabilities()
            except (OSError, V4L2Error) as exc:
                self.controls = None
                return self._fail(msg("engine.error.open_failed", device=device, error=str(exc)))
            if not self.caps["is_capture"]:
                self.close_camera()
                return self._fail(msg("engine.error.not_capture", device=device,
                                      card=self.caps["card"]))
            try:
                self.stream = self._stream_factory(device, self.settings["preview_width"],
                                                    self.settings["preview_height"])
                self.stream.start()
            except (OSError, V4L2Error) as exc:
                self.close_camera()
                if isinstance(exc, OSError) and exc.errno == errno.EBUSY:
                    return self._fail_busy(device)
                return self._fail(msg("engine.error.stream_failed", error=str(exc)))
            self.tracker = self._tracker_factory(self.stream, self.controls, self.tracker_settings())
            self.tracker.start()
            self.vcam.set_source(self.stream)
            if was_tracking and not self.privacy.active:       # privacy resumes tracking itself when it ends
                self.tracker.set_enabled(True)
            self.error, self._busy = None, False
            log.info("camera connected: %s (%s)", self.caps["card"], self.caps["bus_info"])
            return None

    def _fail(self, message: Message) -> Message:
        self.error, self._busy = message, False
        log.error("%s", message.text("en"))
        return message

    def _fail_busy(self, device: str) -> Message:
        who = ", ".join(self._holders(device))
        message = (msg("engine.error.busy", device=device, who=who) if who
                   else msg("engine.error.busy_unknown", device=device))
        if message != self.error:
            log.warning("%s", message.text("en"))
        self.error, self._busy = message, True
        return message

    def close_camera(self) -> None:
        """Stops the tracker before closing the controls - zeroes velocities on ITS OWN controls."""
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

    # --- commands ------------------------------------------------------------

    def set_privacy(self, on: bool) -> None:
        with self._lock:
            if on:
                self.privacy.enable(self.tracker)
            else:
                self.privacy.disable(self.tracker)

    def set_tracking(self, on: bool) -> None:
        with self._lock:
            if self.tracker is None:
                raise LocalizedError("engine.error.no_camera")
            if on and self.privacy.active:
                raise LocalizedError("engine.error.privacy_on")
            self.tracker.set_enabled(on)

    # --- light correction ------------------------------------------------------

    @property
    def light_active(self) -> bool:
        return self._light_lut is not None

    def correct_light(self) -> LightResult:
        """Measure the face in the latest raw camera frame and apply the resulting table.

        Runs on the caller's (worker) thread. A failure leaves the current table unchanged;
        a face that is already well lit removes it. A "restore defaults" while the measurement
        runs wins: its generation token makes this method drop the table."""
        with self._lock:
            stream, tracker = self.stream, self.tracker
            generation = self._light_generation
        if stream is None or tracker is None:
            return LightResult(NO_FRAME)
        try:
            _, jpg, _ = stream.frame_timed(0, timeout=1.0)
            frame = decode_mjpeg(jpg) if jpg is not None else None
            if frame is None:
                return LightResult(NO_FRAME)
            result = analyse(frame, tracker.detect_once(frame), self._selected_point(tracker, frame))
        except Exception:
            log.exception("light correction failed")
            return LightResult(FAILED)
        with self._lock:
            if generation == self._light_generation:      # a reset during the measurement wins
                if result.status == OK:
                    self._set_light(result.lut)
                elif result.status == WELL_LIT:
                    self._set_light(None)
        return result

    def reset_light(self) -> None:
        with self._lock:
            self._light_generation += 1
            self._set_light(None)

    def _set_light(self, lut: np.ndarray | None) -> None:
        """Apply a table to the engine and the virtual camera as one step; callers hold ``_lock``."""
        self._light_lut = lut
        self.vcam.set_tone(lut)

    @staticmethod
    def _selected_point(tracker, frame) -> tuple[float, float] | None:
        """Head point of the person the user selected, in ``frame`` pixels; None in automatic mode
        or when the selected person is not visible. Both frames share the aspect ratio."""
        state = tracker.state
        if state.selection == SELECTION_AUTO or state.target is None or state.frame_size[0] <= 0:
            return None
        scale = frame.shape[1] / state.frame_size[0]
        return state.target.x * scale, state.target.y * scale

    def command(self, cmd: str, arg: str | None = None) -> dict:
        if cmd == "show":
            self.ui.show()
        elif cmd == "hide":
            self.ui.hide()
        elif cmd == "privacy":
            self.set_privacy(_switch(arg, self.privacy.active))
        elif cmd == "tracking":
            self.set_tracking(_switch(arg, bool(self.tracker and self.tracker.enabled)))
        elif cmd == "profile":
            if arg not in PROFILES:
                raise ValueError(f"unknown profile {arg!r} ({', '.join(PROFILES)})")
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
        elif cmd == "select":
            self._select(arg)
        elif cmd == "language":
            self.set_language(arg or "auto")
        elif cmd == "quit":
            self.ui.quit()
        elif cmd != "state":
            raise ValueError(f"unknown command {cmd!r}")
        return self.state()

    def set_language(self, code: str) -> str:
        """Apply and save the UI language; the virtual-camera slates re-render at once."""
        languages = available_languages()
        if code != AUTO and code not in languages:
            raise ValueError(f"unknown language {code!r} ({', '.join([AUTO, *languages])})")
        with self._lock:
            active = set_language(code)
            self.settings["language"] = code
            self.store.save()
            self.vcam.refresh_language()
            return active

    def _select(self, arg: str | None) -> None:
        """``select x,y`` - the person at a frame point (coordinates of ``state.selection.frame``);
        ``select none`` - back to automatic mode."""
        with self._lock:
            if self.tracker is None:
                raise LocalizedError("engine.error.no_camera")
            if arg == "none":
                self.tracker.clear_selection()
                return
            try:
                x, y = (float(v) for v in (arg or "").split(","))
            except ValueError:
                raise ValueError(f"select expects x,y or 'none' (got {arg!r})") from None
            self.tracker.select_at(x, y)

    def state(self) -> dict:
        tracker = self.tracker
        return {
            "camera": tracker is not None,
            "error": self.error.to_dict() if self.error else None,
            "tracking": bool(tracker and tracker.enabled),
            "profile": self.settings["tracking"]["profile"],
            "privacy": self.privacy.active,
            "auto_zoom": self._auto_zoom(),
            "framing": self._framing(tracker),
            "selection": self._selection(tracker),
            "virtual_camera": self.vcam.status.to_dict(),
            "performance": self._performance(tracker),
            "language": get_language(),
        }

    def _auto_zoom(self) -> bool:
        if self.tracker is not None:
            return bool(self.tracker.settings.auto_zoom)
        return bool(self.settings["tracking"]["auto_zoom"])

    @staticmethod
    def _framing(tracker) -> dict | None:
        """Framing (side, shot, yaw, zoom goal) or None when there is no camera."""
        if tracker is None:
            return None
        st = tracker.state
        return {"side": st.side, "shot": st.shot, "yaw": st.yaw, "zoom_goal": st.zoom_goal}

    @staticmethod
    def _selection(tracker) -> dict | None:
        """Person selection: state, number, people in frame and the frame size that ``select x,y`` uses."""
        if tracker is None:
            return None
        st = tracker.state
        note = st.selection_note
        return {"state": st.selection, "id": st.selected_id, "remaining_s": round(st.selection_left, 1),
                "note": note.to_dict() if note else None, "frame": list(st.frame_size),
                "people": [{"id": i.id, "box": list(i.box), "visible": i.visible} for i in st.tracks]}

    @staticmethod
    def _performance(tracker) -> dict | None:
        """Numbers for diagnosing tracking smoothness (also visible in the window)."""
        if tracker is None:
            return None
        st = tracker.state
        return {"hz": round(st.fps, 1), "detection_ms": round(st.detection_ms, 1),
                "loop_ms": round(st.loop_ms, 1), "frame_age_ms": round(st.frame_age_ms, 1),
                "moves": st.moves, "mode": st.mode}
