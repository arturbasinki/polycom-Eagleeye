#!/usr/bin/env python3
"""Tracker thread: motion safety, detector switching, manual control.

Without hardware: a stream double (real JPEG bytes), a controls double,
a perception double.

    .venv/bin/python tests/test_tracker.py
"""

from __future__ import annotations

import sys
import tempfile
import threading
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fakes import FakeControls, TwoPeople  # noqa: E402
from runner import run  # noqa: E402

from eagleeye.detectors import Detection  # noqa: E402
from eagleeye.i18n import msg  # noqa: E402
from eagleeye.tracker import SessionRecorder, Tracker, TrackerSettings, TrackerState, load_session  # noqa: E402
from eagleeye.v4l2 import CID_PAN_ABSOLUTE, CID_PAN_SPEED, CID_ZOOM_ABSOLUTE  # noqa: E402

_ok, _buf = cv2.imencode(".jpg", np.full((360, 640, 3), 90, np.uint8))
JPG = _buf.tobytes()


class FakeStream:
    def __init__(self, jpg: bytes | None = JPG, fps: float = 30.0) -> None:
        self.jpg = jpg
        self.fps = fps
        self.n = 0

    def frame_timed(self, last_id: int = 0, timeout: float = 2.0):
        if self.jpg is None:
            time.sleep(min(timeout, 0.05))
            return last_id, None, 0.0
        time.sleep(1.0 / self.fps)
        self.n += 1
        return self.n, self.jpg, time.monotonic()


class NoPerson:
    last_ms = 0.0
    description = "fake"

    def observe(self, frame, t, previous):
        return None, []


class Broken:
    last_ms = 0.0
    description = "broken"

    def observe(self, frame, t, previous):
        raise RuntimeError("CUDA crashed")


def make(stream=None, controls=None, factory=lambda gpu: NoPerson(), **settings):
    return Tracker(stream or FakeStream(), controls or FakeControls(), TrackerSettings(**settings), factory)


def test_init_stops_leftover_velocity() -> None:
    ctl = FakeControls(x9a0920=15)
    make(controls=ctl)
    assert ctl.writes_to(CID_PAN_SPEED)[:1] == [0]


def test_disabling_during_follow_stops_velocity_immediately() -> None:
    ctl = FakeControls()
    tr = make(controls=ctl)
    tr.set_enabled(True)
    tr.core.actuator.velocity("pan", 1, time.monotonic())
    tr.set_enabled(False)
    assert ctl.writes_to(CID_PAN_SPEED)[-1] == 0


def test_no_frames_stops_motion() -> None:
    ctl = FakeControls()
    tr = make(stream=FakeStream(jpg=None), controls=ctl)
    tr.start()
    try:
        tr.set_enabled(True)
        tr.core.actuator.watchdog_s = 10.0          # we disable the watchdog - we are checking the loop
        tr.core.actuator.velocity("pan", 1, time.monotonic())
        time.sleep(1.4)
        speeds = ctl.writes_to(CID_PAN_SPEED)       # before stop(), which also zeroes the velocity
    finally:
        tr.stop()
    assert tr.state.message.key == "tracker.no_frames"
    assert speeds[-1] == 0


def test_detector_failures_fall_back_to_cpu() -> None:
    requested: list[bool] = []

    def factory(use_gpu: bool):
        requested.append(use_gpu)
        return Broken() if use_gpu else NoPerson()

    tr = make(factory=factory, use_gpu=True)
    tr.start()
    try:
        tr.set_enabled(True)
        time.sleep(0.8)
    finally:
        tr.stop()
    assert requested[0] is True and False in requested
    assert tr.settings.use_gpu is False


def test_manual_move_refused_while_tracking() -> None:
    ctl = FakeControls()
    tr = make(controls=ctl)
    tr.set_enabled(True)
    assert tr.move_to(pan=36000) is False
    tr.set_enabled(False)
    assert tr.move_to(pan=36000) is True
    assert ctl.writes_to(CID_PAN_ABSOLUTE)[-1] == 36000


def test_nudge_moves_relative_to_model() -> None:
    ctl = FakeControls(x9a0908=10000)
    tr = make(controls=ctl)
    assert tr.nudge(3600, 0)
    assert ctl.writes_to(CID_PAN_ABSOLUTE)[-1] == 13600


def test_enabling_starts_search_from_last_azimuth() -> None:
    ctl = FakeControls()
    tr = make(controls=ctl, last_azimuth=(72000.0, 0.0))
    tr.start()
    try:
        tr.set_enabled(True)
        time.sleep(0.3)
    finally:
        tr.stop()
    assert ctl.writes_to(CID_PAN_ABSOLUTE)[0] == 72000


def test_state_is_a_new_snapshot_each_time() -> None:
    tr = make()
    tr.start()
    try:
        first = tr.state
        tr.set_enabled(True)
        time.sleep(0.3)
    finally:
        tr.stop()
    assert tr.state is not first and first.enabled is False


def test_default_state_messages_are_data() -> None:
    state = TrackerState()
    assert state.message == msg("tracker.off") and state.note is None and state.selection_note is None


def test_unexpected_error_stops_motion_and_keeps_thread_alive() -> None:
    ctl = FakeControls()
    tr = make(controls=ctl)
    tr.start()
    try:
        tr.set_enabled(True)
        tr.core.actuator.watchdog_s = 10.0           # the loop is supposed to stop it, not the watchdog
        tr.core.actuator.velocity("pan", 1, time.monotonic())

        def boom(*args, **kwargs):
            raise ZeroDivisionError("error in the director")
        tr.core.step = boom
        time.sleep(0.5)
        speeds = ctl.writes_to(CID_PAN_SPEED)
        alive = tr._thread is not None and tr._thread.is_alive()
    finally:
        tr.stop()
    assert speeds[-1] == 0, "the motion must be stopped"
    assert not tr.enabled and tr.state.message.key == "tracker.failed"
    assert alive, "the thread must survive so that tracking can be enabled again"


def test_recording_can_be_switched_on_while_tracking() -> None:
    """Reported: the "record session" switch worked only after reconnecting."""
    directory = Path(tempfile.mkdtemp())
    tr = make()
    tr.set_enabled(True)
    tr.set_record(True, directory)
    assert tr._recorder is not None and tr._recorder.path.parent == directory
    tr.set_record(False)
    assert tr._recorder is None and len(list(directory.glob("*.jsonl"))) == 1


def test_position_and_tilt_min() -> None:
    ctl = FakeControls(x9a0908=36000, x9a0909=-3600)
    tr = make(controls=ctl)
    assert tr.position() == (36000, -3600)
    assert tr.tilt_min() == -108000


def test_recorder_round_trip() -> None:
    directory = Path(tempfile.mkdtemp())
    rec = SessionRecorder.create(directory)
    rec.write(1.25, (100.0, -50.0), [], "tracking")
    rec.write(1.30, None, [], "lost")
    rec.close()
    rows = load_session(rec.path)
    assert rows[0]["world"] == [100.0, -50.0] and rows[1]["world"] is None


def test_initial_state_reports_auto_zoom_setting() -> None:
    assert make(auto_zoom=True).state.auto_zoom is True
    assert make(auto_zoom=False).state.auto_zoom is False


def test_manual_zoom_while_tracking_turns_auto_zoom_off() -> None:
    ctl = FakeControls()
    tr = make(controls=ctl, auto_zoom=True)
    tr.start()
    try:
        tr.set_enabled(True)
        ctl.values[CID_ZOOM_ABSOLUTE] = 3000       # someone turned the zoom ring
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            if tr.core.director.auto_zoom is False and tr.settings.auto_zoom is False:
                break
            time.sleep(0.05)
    finally:
        tr.stop()
    assert tr.core.director.auto_zoom is False and tr.settings.auto_zoom is False
    assert tr.state.auto_zoom is False


def test_set_auto_zoom_updates_director_and_state() -> None:
    tr = make(auto_zoom=False)
    assert tr.core.director.auto_zoom is False
    tr.set_auto_zoom(True)
    assert tr.settings.auto_zoom is True and tr.core.director.auto_zoom is True
    assert tr.state.auto_zoom is True


def test_recorder_writes_framing_fields() -> None:
    directory = Path(tempfile.mkdtemp())
    rec = SessionRecorder.create(directory)
    rec.write(1.0, (0.0, 0.0), [], "tracking", {"yaw": 0.4, "side": "left"})
    rec.close()
    rows = load_session(rec.path)
    assert rows[0]["yaw"] == 0.4 and rows[0]["side"] == "left"



def _wait_until(cond, timeout: float = 3.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def _two_people_tracker(**settings):
    fake = TwoPeople()
    tr = make(factory=lambda gpu: fake, **settings)
    tr.set_enabled(True)
    tr.start()
    assert _wait_until(lambda: len(tr.state.tracks) == 2 and tr.state.target is not None)
    return tr, fake


def test_click_selects_one_of_two_people_and_clear_returns_to_auto() -> None:
    tr, fake = _two_people_tracker()
    try:
        assert tr.state.target.box == fake.left.as_box(), "AUTO: the biggest person"
        assert tr.select_at(220, 80) is True
        assert _wait_until(lambda: tr.state.selection == "selected" and tr.state.target is not None
                           and tr.state.target.box == fake.right.as_box())
        assert tr.select_at(5, 5) is False and tr.state.selection == "selected", "an empty spot changes nothing"
        tr.clear_selection()
        assert _wait_until(lambda: tr.state.selection == "auto" and tr.state.target is not None
                           and tr.state.target.box == fake.left.as_box())
    finally:
        tr.stop()


def test_selected_person_leaving_suspends_then_expires_to_auto() -> None:
    tr, fake = _two_people_tracker()
    tr.set_select_hold(1.3)
    try:
        assert tr.select_at(220, 80)
        assert _wait_until(lambda: tr.state.selection == "selected")
        fake.dets = [fake.left]                          # the selected person leaves the frame
        assert _wait_until(lambda: tr.state.selection == "suspended")
        assert tr.state.target is None, "the camera stays put, it does not switch to the other person"
        assert _wait_until(lambda: tr.state.selection == "auto", timeout=4.0)
        assert tr.state.selection_note == msg("identity.selection_lost")
        assert _wait_until(lambda: tr.state.target is not None and tr.state.target.box == fake.left.as_box())
    finally:
        tr.stop()


def test_selected_person_returning_is_tracked_again() -> None:
    tr, fake = _two_people_tracker()
    try:
        assert tr.select_at(220, 80)
        assert _wait_until(lambda: tr.state.selection == "selected")
        fake.dets = [fake.left]
        assert _wait_until(lambda: tr.state.selection == "suspended")
        fake.dets = [fake.left, fake.right]              # returns to the same spot
        assert _wait_until(lambda: tr.state.selection == "selected" and tr.state.target is not None
                           and tr.state.target.box == fake.right.as_box())
    finally:
        tr.stop()


def test_disabling_tracking_clears_the_selection() -> None:
    tr, _ = _two_people_tracker()
    try:
        assert tr.select_at(220, 80)
        assert _wait_until(lambda: tr.state.selection == "selected")
        tr.set_enabled(False)
        assert _wait_until(lambda: tr.state.selection == "auto" and tr.state.tracks == ())
        tr.set_enabled(True)
        assert _wait_until(lambda: len(tr.state.tracks) == 2)
        assert tr.state.selection == "auto" and tr.state.selected_id is None
    finally:
        tr.stop()


def test_identity_error_returns_to_auto_and_keeps_running() -> None:
    tr, fake = _two_people_tracker()
    try:
        assert tr.select_at(220, 80)
        assert _wait_until(lambda: tr.state.selection == "selected")
        fake.fail_observation = True                     # numbering raises on the selected person
        assert _wait_until(lambda: tr.state.selection == "auto"
                           and tr.state.selection_note == msg("tracker.identity_error"))
        assert tr.enabled and tr.state.enabled
    finally:
        tr.stop()


def test_identity_is_frozen_while_the_zoom_is_moving() -> None:
    """While the zoom is moving, the field of view from the control is not real (as in core.step):
    numbering does not rescale positions or sizes then, and the selection does not hand the
    target to a stranger."""
    tr, fake = _two_people_tracker()
    try:
        assert tr.select_at(220, 80)
        assert _wait_until(lambda: tr.state.selection == "selected")
        tr.core.actuator.zoom_model.moving = lambda t: True
        time.sleep(0.2)
        fake.dets = [fake.left, fake.right, Detection(120, 30, 40, 120, 0.9, "pose")]
        time.sleep(0.4)
        assert len(tr.state.tracks) == 2, "the third person gets no number while the zoom is moving"
        assert tr.state.target is None or tr.state.target.box == fake.right.as_box()
        del tr.core.actuator.zoom_model.moving          # end of the move: we count again
        assert _wait_until(lambda: len(tr.state.tracks) == 3)
    finally:
        tr.stop()


class Detecting:
    """Perception double that also answers detect() and notices overlapping calls."""

    last_ms = 0.0
    description = "fake"

    def __init__(self) -> None:
        self.busy = False
        self.overlaps = 0
        self.calls = 0

    def observe(self, frame, t, previous):
        return None, []

    def detect(self, frame):
        if self.busy:
            self.overlaps += 1
        self.busy = True
        time.sleep(0.01)
        self.calls += 1
        self.busy = False
        return [Detection(10, 10, 20, 40, 0.9, "pose")]


def test_detect_once_creates_the_detector_lazily_and_reuses_it() -> None:
    created: list[Detecting] = []

    def factory(gpu):
        created.append(Detecting())
        return created[-1]

    tr = make(factory=factory)
    frame = np.zeros((36, 64, 3), np.uint8)
    assert created == []
    assert len(tr.detect_once(frame)) == 1 and len(created) == 1
    tr.detect_once(frame)
    assert len(created) == 1 and created[0].calls == 2


def test_detect_once_takes_turns_with_other_threads() -> None:
    det = Detecting()
    tr = make(factory=lambda gpu: det)
    frame = np.zeros((36, 64, 3), np.uint8)
    threads = [threading.Thread(target=tr.detect_once, args=(frame,)) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert det.calls == 6 and det.overlaps == 0


if __name__ == "__main__":
    run(globals(), "Tracker thread")