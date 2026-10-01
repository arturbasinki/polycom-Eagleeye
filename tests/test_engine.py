#!/usr/bin/env python3
"""Silnik: kamera, polecenia, prywatność, stan - bez sprzętu i bez okna.

    .venv/bin/python tests/test_engine.py
"""

from __future__ import annotations

import errno
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fakes import FakeCameraStream, FakeControls, TwoPeople  # noqa: E402
from runner import run  # noqa: E402

from eagleeye.config import Store  # noqa: E402
from eagleeye.engine import Engine, UiHooks  # noqa: E402
from eagleeye.tracker import Tracker  # noqa: E402
from eagleeye.v4l2 import CID_TILT_ABSOLUTE  # noqa: E402


class NoPerson:
    last_ms = 0.0
    description = "atrapa"

    def observe(self, frame, t, previous):
        return None, []


class FakeVcam:
    def __init__(self) -> None:
        self.source = None
        self.privacy = False
        self.status = "działa"
        self.running = False

    def set_source(self, stream) -> None:
        self.source = stream

    def set_privacy(self, on: bool) -> None:
        self.privacy = on

    def start(self) -> None:
        self.running = True

    def stop(self) -> None:
        self.running = False


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
        assert engine.state()["kamera"] is True
        assert set(engine.state()["wydajnosc"]) >= {"hz", "detekcja_ms", "wiek_klatki_ms", "ruchy"}
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
        assert state["kamera"] is False and "nie mogę otworzyć" in state["blad"]
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
        assert state["kamera"] is False
        assert "chrome" in state["blad"] and "EagleEye" in state["blad"]
        busy[0] = False                          # w Meet wybrano kamerę EagleEye - Chrome zwolnił urządzenie
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
        assert len(calls) == 1                   # zły wybór urządzenia - nie ponawiamy w kółko
    finally:
        engine.shutdown()


def test_privacy_command_shows_card_and_parks_head() -> None:
    engine, ctl = make_engine()
    engine.start()
    try:
        state = engine.command("prywatnosc")
        assert state["prywatnosc"] is True and engine.vcam.privacy
        assert ctl.writes_to(CID_TILT_ABSOLUTE)[-1] == -108000
        state = engine.command("prywatnosc", "wyl")
        assert state["prywatnosc"] is False and not engine.vcam.privacy
    finally:
        engine.shutdown()


def test_privacy_without_camera_still_shows_card() -> None:
    def broken(device):
        raise OSError(2, "brak")
    engine, _ = make_engine(controls_factory=broken)
    engine.start()
    try:
        assert engine.command("prywatnosc", "wl")["prywatnosc"] is True and engine.vcam.privacy
    finally:
        engine.shutdown()


def test_shutdown_during_privacy_returns_head_without_tracking() -> None:
    engine, ctl = make_engine()
    engine.start()
    ctl.values[CID_TILT_ABSOLUTE] = 50000
    engine.tracker.core.actuator.sync_from_device(0.0)
    engine.tracker.set_enabled(True)
    engine.command("prywatnosc", "wl")
    tracker = engine.tracker
    engine.shutdown(park_wait=0.0)
    assert ctl.writes_to(CID_TILT_ABSOLUTE)[-1] == 50000      # obiektyw wraca z pozycji "w dół"
    assert not tracker.enabled                                 # bez wznawiania śledzenia przy wyjściu


def test_tracking_is_blocked_during_privacy() -> None:
    engine, _ = make_engine()
    engine.start()
    try:
        engine.command("prywatnosc", "wl")
        try:
            engine.command("sledzenie", "wl")
        except RuntimeError as exc:
            assert "prywatno" in str(exc)
        else:
            raise AssertionError("śledzenie nie powinno ruszyć w trakcie prywatności")
    finally:
        engine.shutdown()


def test_tracking_command_toggles() -> None:
    engine, _ = make_engine()
    engine.start()
    try:
        assert engine.command("sledzenie", "wl")["sledzenie"] is True
        assert engine.command("sledzenie")["sledzenie"] is False
    finally:
        engine.shutdown()


def test_profile_command_validates_and_saves() -> None:
    engine, _ = make_engine()
    engine.start()
    try:
        assert engine.command("profil", "presentation")["profil"] == "presentation"
        saved = json.loads(engine.store.path.read_text(encoding="utf-8"))
        assert saved["settings"]["tracking"]["profile"] == "presentation"
        try:
            engine.command("profil", "nieistniejący")
        except ValueError:
            pass
        else:
            raise AssertionError("oczekiwano ValueError")
    finally:
        engine.shutdown()


def test_autozoom_command_toggles_and_saves() -> None:
    engine, _ = make_engine()
    engine.start()
    try:
        assert engine.command("autozoom", "wyl")["zoom_auto"] is False
        saved = json.loads(engine.store.path.read_text(encoding="utf-8"))
        assert saved["settings"]["tracking"]["auto_zoom"] is False
        assert engine.tracker.core.director.auto_zoom is False
        assert engine.command("autozoom")["zoom_auto"] is True
    finally:
        engine.shutdown()


def test_manual_zoom_turns_auto_zoom_off_in_state() -> None:
    engine, _ = make_engine()
    engine.start()
    try:
        engine.tracker.core.director.auto_zoom = False
        engine.tracker.settings.auto_zoom = False
        state = engine.state()
        assert state["zoom_auto"] is False and "kadr" in state
    finally:
        engine.shutdown()


def test_unknown_command_raises() -> None:
    engine, _ = make_engine()
    try:
        engine.command("nie-ma-takiego")
    except ValueError:
        return
    raise AssertionError("oczekiwano ValueError")


def test_window_commands_use_ui_hooks() -> None:
    engine, _ = make_engine()
    calls = []
    engine.ui = UiHooks(show=lambda: calls.append("pokaz"), hide=lambda: calls.append("schowaj"),
                        quit=lambda: calls.append("zakoncz"))
    for cmd in ("pokaz", "schowaj", "zakoncz"):
        engine.command(cmd)
    assert calls == ["pokaz", "schowaj", "zakoncz"]



def _wait_until(cond, timeout: float = 3.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_wybierz_selects_a_person_and_state_lists_people() -> None:
    engine, _ = make_engine(perception=TwoPeople)
    engine.start()
    try:
        engine.command("sledzenie", "wl")
        assert _wait_until(lambda: len(engine.state()["wybor"]["osoby"]) == 2)
        wybor = engine.state()["wybor"]
        assert wybor["stan"] == "auto" and wybor["klatka"] == [640, 360]
        assert all(o["widoczna"] and len(o["ramka"]) == 4 for o in wybor["osoby"])
        engine.command("wybierz", "220,80")
        assert _wait_until(lambda: engine.state()["wybor"]["stan"] == "selected")
        assert engine.state()["wybor"]["id"] is not None
        engine.command("wybierz", "brak")
        assert _wait_until(lambda: engine.state()["wybor"]["stan"] == "auto")
    finally:
        engine.shutdown()


def test_wybierz_rejects_bad_arguments() -> None:
    engine, _ = make_engine(perception=TwoPeople)
    engine.start()
    try:
        for bad in (None, "abc", "1", "1,2,3"):
            try:
                engine.command("wybierz", bad)
            except ValueError:
                continue
            raise AssertionError(f"wybierz {bad!r} powinno zgłosić ValueError")
    finally:
        engine.shutdown()


def test_wybierz_without_camera_is_an_error_and_state_has_no_selection() -> None:
    def broken(device):
        raise OSError(2, "No such file or directory")
    engine, _ = make_engine(controls_factory=broken)
    engine.start()
    try:
        assert engine.state()["wybor"] is None
        try:
            engine.command("wybierz", "1,2")
        except RuntimeError as exc:
            assert "niepodłączona" in str(exc)
        else:
            raise AssertionError("bez kamery wybierz powinno zgłosić RuntimeError")
    finally:
        engine.shutdown()


def test_select_hold_setting_reaches_the_tracker() -> None:
    engine, _ = make_engine()
    engine.settings["tracking"]["select_hold_s"] = 9
    assert engine.tracker_settings().select_hold_s == 9.0

if __name__ == "__main__":
    run(globals(), "Silnik")
