#!/usr/bin/env python3
"""Engine: camera, commands, privacy, state - without hardware and without a window.

    .venv/bin/python tests/test_engine.py
"""

from __future__ import annotations

import errno
import json
import sys
import tempfile
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fakes import FakeCameraStream, FakeControls, TwoPeople, face_scene  # noqa: E402
from runner import run  # noqa: E402

from eagleeye import i18n  # noqa: E402
from eagleeye.config import Store  # noqa: E402
from eagleeye.engine import Engine, UiHooks  # noqa: E402
from eagleeye.i18n import LocalizedError, msg, render  # noqa: E402
from eagleeye.tracker import Tracker  # noqa: E402
from eagleeye.v4l2 import CID_TILT_ABSOLUTE  # noqa: E402


class NoPerson:
    last_ms = 0.0
    description = "fake"

    def observe(self, frame, t, previous):
        return None, []


class FakeVcam:
    def __init__(self) -> None:
        self.source = None
        self.privacy = False
        self.status = msg("vcam.status.running")
        self.running = False
        self.refreshed = 0
        self.tone = None

    def set_source(self, stream) -> None:
        self.source = stream

    def set_privacy(self, on: bool) -> None:
        self.privacy = on

    def start(self) -> None:
        self.running = True

    def stop(self) -> None:
        self.running = False

    def refresh_language(self) -> None:
        self.refreshed += 1

    def set_tone(self, lut) -> None:
        self.tone = lut


def make_engine(controls_factory=None, stream_factory=FakeCameraStream, perception=NoPerson, **kwargs):
    path = Path(tempfile.mkdtemp()) / "config.json"
    path.write_text(json.dumps({"settings": {}, "presets": []}), encoding="utf-8")
    ctl = FakeControls()
    engine = Engine(Store(path), stream_factory=stream_factory, **kwargs,
                    controls_factory=controls_factory or (lambda device: ctl),
                    tracker_factory=lambda s, c, st: Tracker(s, c, st, lambda gpu: perception()),
                    vcam=FakeVcam())
    return engine, ctl


def test_start_opens_camera_and_feeds_virtual_camera() -> None:
    engine, _ = make_engine()
    engine.start()
    try:
        assert engine.error is None and engine.tracker is not None
        assert engine.vcam.running and engine.vcam.source is engine.stream
        assert engine.state()["camera"] is True
        assert set(engine.state()["performance"]) >= {"hz", "detection_ms", "frame_age_ms", "moves"}
    finally:
        engine.shutdown()
    assert engine.vcam.source is None and not engine.vcam.running


def test_open_failure_is_reported_without_crash() -> None:
    def broken(device):
        raise OSError(2, "No such file or directory")
    engine, _ = make_engine(controls_factory=broken)
    engine.start()
    try:
        state = engine.state()
        assert state["camera"] is False and state["error"]["key"] == "engine.error.open_failed"
    finally:
        engine.shutdown()


def test_busy_camera_names_holder_and_reconnects_by_itself() -> None:
    busy = [True]

    def stream_factory(device, w, h):
        if busy[0]:
            raise OSError(errno.EBUSY, "Device or resource busy")
        return FakeCameraStream(device, w, h)

    engine, _ = make_engine(stream_factory=stream_factory, busy_retry_s=0.05,
                            holders=lambda device: ["chrome"])
    engine.start()
    try:
        state = engine.state()
        assert state["camera"] is False
        text = render(state["error"])
        assert "chrome" in text and "EagleEye" in text
        busy[0] = False                          # in Meet the EagleEye camera was chosen - Chrome released the device
        deadline = time.monotonic() + 2.0
        while (engine.tracker is None or engine.error) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert engine.tracker is not None and engine.error is None
    finally:
        engine.shutdown()


def test_other_open_errors_do_not_retry() -> None:
    calls = []

    def broken(device):
        calls.append(device)
        raise OSError(2, "No such file or directory")
    engine, _ = make_engine(controls_factory=broken, busy_retry_s=0.02)
    engine.start()
    try:
        time.sleep(0.2)
        assert len(calls) == 1                   # a wrong device choice - we do not retry in a loop
    finally:
        engine.shutdown()


def test_privacy_command_shows_card_and_parks_head() -> None:
    engine, ctl = make_engine()
    engine.start()
    try:
        state = engine.command("privacy")
        assert state["privacy"] is True and engine.vcam.privacy
        assert ctl.writes_to(CID_TILT_ABSOLUTE)[-1] == -108000
        state = engine.command("privacy", "off")
        assert state["privacy"] is False and not engine.vcam.privacy
    finally:
        engine.shutdown()


def test_privacy_without_camera_still_shows_card() -> None:
    def broken(device):
        raise OSError(2, "missing")
    engine, _ = make_engine(controls_factory=broken)
    engine.start()
    try:
        assert engine.command("privacy", "on")["privacy"] is True and engine.vcam.privacy
    finally:
        engine.shutdown()


def test_shutdown_during_privacy_returns_head_without_tracking() -> None:
    engine, ctl = make_engine()
    engine.start()
    ctl.values[CID_TILT_ABSOLUTE] = 50000
    engine.tracker.core.actuator.sync_from_device(0.0)
    engine.tracker.set_enabled(True)
    engine.command("privacy", "on")
    tracker = engine.tracker
    engine.shutdown(park_wait=0.0)
    assert ctl.writes_to(CID_TILT_ABSOLUTE)[-1] == 50000      # the lens returns from the "down" position
    assert not tracker.enabled                                 # without resuming tracking on exit


def test_tracking_is_blocked_during_privacy() -> None:
    engine, _ = make_engine()
    engine.start()
    try:
        engine.command("privacy", "on")
        try:
            engine.command("tracking", "on")
        except LocalizedError as exc:
            assert exc.message == msg("engine.error.privacy_on")
        else:
            raise AssertionError("tracking must not start while privacy is on")
    finally:
        engine.shutdown()


def test_tracking_command_toggles() -> None:
    engine, _ = make_engine()
    engine.start()
    try:
        assert engine.command("tracking", "on")["tracking"] is True
        assert engine.command("tracking")["tracking"] is False
    finally:
        engine.shutdown()


def test_profile_command_validates_and_saves() -> None:
    engine, _ = make_engine()
    engine.start()
    try:
        assert engine.command("profile", "presentation")["profile"] == "presentation"
        saved = json.loads(engine.store.path.read_text(encoding="utf-8"))
        assert saved["settings"]["tracking"]["profile"] == "presentation"
        try:
            engine.command("profile", "nonexistent")
        except ValueError:
            pass
        else:
            raise AssertionError("expected ValueError")
    finally:
        engine.shutdown()


def test_autozoom_command_toggles_and_saves() -> None:
    engine, _ = make_engine()
    engine.start()
    try:
        assert engine.command("autozoom", "off")["auto_zoom"] is False
        saved = json.loads(engine.store.path.read_text(encoding="utf-8"))
        assert saved["settings"]["tracking"]["auto_zoom"] is False
        assert engine.tracker.core.director.auto_zoom is False
        assert engine.command("autozoom")["auto_zoom"] is True
    finally:
        engine.shutdown()


def test_manual_zoom_turns_auto_zoom_off_in_state() -> None:
    engine, _ = make_engine()
    engine.start()
    try:
        engine.tracker.core.director.auto_zoom = False
        engine.tracker.settings.auto_zoom = False
        state = engine.state()
        assert state["auto_zoom"] is False and "framing" in state
    finally:
        engine.shutdown()


def test_unknown_command_raises() -> None:
    engine, _ = make_engine()
    try:
        engine.command("no-such-command")
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_window_commands_use_ui_hooks() -> None:
    engine, _ = make_engine()
    calls = []
    engine.ui = UiHooks(show=lambda: calls.append("show"), hide=lambda: calls.append("hide"),
                        quit=lambda: calls.append("quit"))
    for cmd in ("show", "hide", "quit"):
        engine.command(cmd)
    assert calls == ["show", "hide", "quit"]



def _wait_until(cond, timeout: float = 3.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_select_selects_a_person_and_state_lists_people() -> None:
    engine, _ = make_engine(perception=TwoPeople)
    engine.start()
    try:
        engine.command("tracking", "on")
        assert _wait_until(lambda: len(engine.state()["selection"]["people"]) == 2)
        selection = engine.state()["selection"]
        assert selection["state"] == "auto" and selection["frame"] == [640, 360]
        assert all(o["visible"] and len(o["box"]) == 4 for o in selection["people"])
        engine.command("select", "220,80")
        assert _wait_until(lambda: engine.state()["selection"]["state"] == "selected")
        assert engine.state()["selection"]["id"] is not None
        engine.command("select", "none")
        assert _wait_until(lambda: engine.state()["selection"]["state"] == "auto")
    finally:
        engine.shutdown()


def test_select_rejects_bad_arguments() -> None:
    engine, _ = make_engine(perception=TwoPeople)
    engine.start()
    try:
        for bad in (None, "abc", "1", "1,2,3"):
            try:
                engine.command("select", bad)
            except ValueError:
                continue
            raise AssertionError(f"select {bad!r} must raise ValueError")
    finally:
        engine.shutdown()


def test_select_without_camera_is_an_error_and_state_has_no_selection() -> None:
    def broken(device):
        raise OSError(2, "No such file or directory")
    engine, _ = make_engine(controls_factory=broken)
    engine.start()
    try:
        assert engine.state()["selection"] is None
        try:
            engine.command("select", "1,2")
        except LocalizedError as exc:
            assert exc.message == msg("engine.error.no_camera")
        else:
            raise AssertionError("select without a camera must raise LocalizedError")
    finally:
        engine.shutdown()


def test_select_hold_setting_reaches_the_tracker() -> None:
    engine, _ = make_engine()
    engine.settings["tracking"]["select_hold_s"] = 9
    assert engine.tracker_settings().select_hold_s == 9.0


def test_state_is_json_and_independent_of_the_language() -> None:
    def broken(device):
        raise OSError(errno.EACCES, "Permission denied")
    engine, _ = make_engine(controls_factory=broken)
    engine.start()                  # camera fails: the state carries an error message, no timing numbers
    try:
        i18n.set_language("en")
        english = json.dumps(engine.state(), ensure_ascii=False, sort_keys=True)
        i18n.set_language("pl")
        polish = json.dumps(engine.state(), ensure_ascii=False, sort_keys=True)
    finally:
        i18n.set_language("en")
        engine.shutdown()
    assert english.replace('"language": "en"', "") == polish.replace('"language": "pl"', ""), \
        "state must carry codes and messages, never rendered text"


def test_errors_are_messages_and_survive_odd_characters() -> None:
    def broken(device):
        raise OSError(errno.EACCES, "brak dostępu {x} ł")    # polish: deliberate
    engine, _ = make_engine(controls_factory=broken)
    engine.start()
    try:
        assert engine.error.key == "engine.error.open_failed"
        wire = json.dumps(engine.state(), ensure_ascii=False)
        assert "brak dostępu {x} ł" in wire    # polish: deliberate
        assert "brak dostępu {x} ł" in engine.error.text("pl")     # braces in a parameter must not break formatting; polish: deliberate
    finally:
        engine.shutdown()


def test_legacy_profile_value_falls_back_to_the_default() -> None:
    path = Path(tempfile.mkdtemp()) / "config.json"
    path.write_text(json.dumps({"settings": {"tracking": {"profile": "rozmowa"}}, "presets": []}),    # polish: deliberate
                    encoding="utf-8")
    engine = Engine(Store(path), stream_factory=FakeCameraStream,
                    controls_factory=lambda device: FakeControls(),
                    tracker_factory=lambda s, c, st: Tracker(s, c, st, lambda gpu: NoPerson()),
                    vcam=FakeVcam())
    assert engine.state()["profile"] == "talk"
    assert engine.settings["tracking"]["profile"] == "talk"


def test_language_command_switches_saves_and_refreshes_the_slates() -> None:
    engine, _ = make_engine()
    try:
        assert engine.command("language", "pl")["language"] == "pl"
        saved = json.loads(engine.store.path.read_text(encoding="utf-8"))
        assert saved["settings"]["language"] == "pl" and engine.vcam.refreshed == 1
        assert engine.command("language", "auto")["language"] in ("en", "pl")
    finally:
        i18n.set_language("en")


def test_language_command_rejects_unknown_codes() -> None:
    engine, _ = make_engine()
    before = engine.settings["language"]
    try:
        engine.command("language", "klingon")
    except ValueError as exc:
        assert "klingon" in str(exc) and "auto" in str(exc)
    else:
        raise AssertionError("expected ValueError")
    assert engine.settings["language"] == before and engine.vcam.refreshed == 0, "nothing may be saved or refreshed"


def test_command_errors_carry_a_message() -> None:
    def broken(device):
        raise OSError(errno.ENOENT, "No such file or directory")
    engine, _ = make_engine(controls_factory=broken)
    engine.start()                  # no camera: tracker is None
    try:
        engine.command("tracking", "on")
        raise AssertionError("expected LocalizedError")
    except LocalizedError as exc:
        assert exc.message == msg("engine.error.no_camera")
    finally:
        engine.shutdown()


class LightPerception:
    """Perception double for the light correction: fixed detections, optional failure."""

    last_ms = 0.0
    description = "fake"

    def __init__(self, dets, fail: bool = False) -> None:
        self.dets = dets
        self.fail = fail

    def observe(self, frame, t, previous):
        return None, list(self.dets)

    def detect(self, frame):
        if self.fail:
            raise RuntimeError("detector crashed")
        return list(self.dets)


def light_engine(skin_y: int, dets=None, fail: bool = False):
    frame, det = face_scene(skin_y)
    ok, buf = cv2.imencode(".jpg", frame)
    jpg = buf.tobytes()

    class Stream(FakeCameraStream):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self.jpg = jpg

    people = [det] if dets is None else dets
    return make_engine(stream_factory=Stream, perception=lambda: LightPerception(people, fail))


def test_correct_light_sets_the_tone_table_on_the_virtual_camera() -> None:
    engine, _ = light_engine(40)
    engine.start()
    try:
        result = engine.correct_light()
        assert result.status == "ok" and engine.light_active
        assert np.array_equal(engine.vcam.tone, result.lut) and engine.light_lut is not None
    finally:
        engine.shutdown()


def test_correct_light_on_a_well_lit_face_clears_an_existing_table() -> None:
    engine, _ = light_engine(120)
    engine.start()
    try:
        table = np.arange(256, dtype=np.uint8)
        engine._light_lut = table
        engine.vcam.set_tone(table)
        assert engine.correct_light().status == "well_lit"
        assert not engine.light_active and engine.vcam.tone is None
    finally:
        engine.shutdown()


def test_correct_light_failures_leave_the_table_unchanged() -> None:
    engine, _ = light_engine(40, dets=[])
    engine.start()
    try:
        assert engine.correct_light().status == "no_person" and engine.vcam.tone is None
    finally:
        engine.shutdown()
    engine, _ = light_engine(40, fail=True)
    engine.start()
    try:
        assert engine.correct_light().status == "failed" and engine.vcam.tone is None
    finally:
        engine.shutdown()
    engine, _ = make_engine()
    assert engine.correct_light().status == "no_frame"          # camera never opened


def test_reset_light_clears_the_table() -> None:
    engine, _ = light_engine(40)
    engine.start()
    try:
        engine.correct_light()
        engine.reset_light()
        assert not engine.light_active and engine.vcam.tone is None and engine.light_lut is None
    finally:
        engine.shutdown()


def test_light_survives_a_camera_reopen() -> None:
    engine, _ = light_engine(40)
    engine.start()
    try:
        engine.correct_light()
        assert engine.open_camera() is None
        assert engine.light_active and engine.vcam.tone is not None
    finally:
        engine.shutdown()


def test_selected_point_scales_the_tracker_target_to_the_frame() -> None:
    from types import SimpleNamespace

    frame = np.zeros((360, 640, 3), np.uint8)
    auto = SimpleNamespace(state=SimpleNamespace(selection="auto", target=SimpleNamespace(x=100.0, y=50.0),
                                                 frame_size=(320, 180)))
    assert Engine._selected_point(auto, frame) is None
    chosen = SimpleNamespace(state=SimpleNamespace(selection="selected", target=SimpleNamespace(x=100.0, y=50.0),
                                                   frame_size=(320, 180)))
    assert Engine._selected_point(chosen, frame) == (200.0, 100.0)
    suspended = SimpleNamespace(state=SimpleNamespace(selection="suspended", target=None, frame_size=(320, 180)))
    assert Engine._selected_point(suspended, frame) is None


def test_reset_during_a_correction_wins() -> None:
    engine, _ = light_engine(40)
    engine.start()
    try:
        original = Engine._selected_point
        engine._selected_point = lambda tracker, frame: (engine.reset_light(), original(tracker, frame))[1]
        assert engine.correct_light().status == "ok"
        assert not engine.light_active and engine.vcam.tone is None
    finally:
        engine.shutdown()


def test_a_failure_keeps_an_existing_table() -> None:
    engine, _ = light_engine(40, dets=[])
    engine.start()
    try:
        table = np.arange(256, dtype=np.uint8)
        engine._light_lut = table
        engine.vcam.set_tone(table)
        assert engine.correct_light().status == "no_person"
        assert engine.light_active and np.array_equal(engine.vcam.tone, table)
    finally:
        engine.shutdown()


if __name__ == "__main__":
    run(globals(), "Engine")
