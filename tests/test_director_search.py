#!/usr/bin/env python3
"""Reżyser: kalibracja startowa (skan), drabina utraty celu, powrót zoomu.

    .venv/bin/python tests/test_director_search.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from runner import run  # noqa: E402

from eagleeye.director import (ALERT, BRAKING, FOLLOWING, IDLE, LOST, MOVING, RESCAN_AFTER,  # noqa: E402
                               SEARCH_DWELL, SEARCHING, TRACKING, WAITING, WORK_TILT_DEFAULT,
                               Director, Limits)
from eagleeye.geometry import View, deg  # noqa: E402
from eagleeye.head_model import Dynamics, HeadModel  # noqa: E402
from eagleeye.i18n import Message  # noqa: E402
from eagleeye.profiles import PRESENTATION, TALK  # noqa: E402
from eagleeye.search import startup_plan  # noqa: E402
from eagleeye.target_filter import TargetEstimate  # noqa: E402

DYN = Dynamics()
LIM = Limits(-deg(170), deg(170), -deg(30), deg(90))
DT = 1 / 15


class Rig:
    """Reżyser + model głowicy + zoom, który zmienia się po rozkazach."""

    def __init__(self, profile, zoom: float = 0.0, pan: float = 0.0) -> None:
        self.d = Director(profile, LIM, DYN)
        self.h = HeadModel(DYN, pan=pan)
        self.zoom = zoom
        self.log: list = []

    def view(self) -> View:
        return View(1280, 720, zoom_value=self.zoom)

    def run(self, seconds: float, est_fn, t0: float = 0.0) -> float:
        n = int(seconds / DT)
        for i in range(n):
            t = t0 + i * DT
            cmds = self.d.tick(t, est_fn(t, self), self.h, self.view())
            for c in cmds:
                if c.kind == "abs":
                    self.h.command_absolute(c.axis, c.value, t)
                elif c.kind == "vel":
                    self.h.command_velocity(c.axis, int(c.value), t)
                else:
                    self.zoom = c.value
            self.log += [(t, c) for c in cmds]
        return t0 + n * DT


def nobody(t, rig):
    return None


def visible_at(pan: float, tilt: float):
    """Osoba stoi w (pan, tilt); widać ją, gdy kamera stoi i ma ją w kadrze."""
    def fn(t, rig):
        cam_pan, cam_tilt = rig.h.angles(t)
        v = rig.view()
        if rig.h.moving("pan", t) or rig.h.moving("tilt", t):
            return None
        if abs(pan - cam_pan) < v.hfov / 2 and abs(tilt - cam_tilt) < v.vfov / 2:
            return TargetEstimate(pan, tilt, 0.0, 0.0, t, t)
        return None
    return fn


def test_start_search_begins_at_last_azimuth() -> None:
    r = Rig(TALK)
    r.d.last_azimuth = (deg(30), 0.0)
    r.d.start_search(0.0, 0.0)
    r.run(DT, nobody)
    first = [c for _, c in r.log if c.kind == "abs"]
    assert (first[0].axis, first[0].value) == ("pan", deg(30))
    assert (first[1].axis, first[1].value) == ("tilt", WORK_TILT_DEFAULT)


def test_search_visits_every_point_with_dwell() -> None:
    r = Rig(TALK)
    r.d.start_search(0.0, 0.0)
    r.run(90.0, nobody)
    pans = [(t, c.value) for t, c in r.log if c.kind == "abs" and c.axis == "pan"]
    plan = startup_plan(0.0, WORK_TILT_DEFAULT, LIM.bounds("pan"), LIM.bounds("tilt"))
    assert [p for _, p in pans[:len(plan)]] == [p for p, _ in plan]
    gaps = [b[0] - a[0] for a, b in zip(pans, pans[1:len(plan)])]
    assert min(gaps) >= SEARCH_DWELL


def test_search_stops_when_person_is_found() -> None:
    r = Rig(TALK)
    r.d.start_search(0.0, 0.0)
    r.run(20.0, visible_at(deg(60), WORK_TILT_DEFAULT))
    pans = [c.value for _, c in r.log if c.kind == "abs" and c.axis == "pan"]
    assert pans[:2] == [0.0, deg(60)] and len(pans) == 2
    assert r.d.status.mode == TRACKING


def test_search_zooms_out_and_restores_zoom_after_find() -> None:
    r = Rig(TALK, zoom=1000.0)
    r.d.start_search(0.0, 1000.0)
    r.run(10.0, visible_at(0.0, WORK_TILT_DEFAULT))
    zooms = [c.value for _, c in r.log if c.kind == "zoom"]
    assert zooms == [0.0, 1000.0]


def test_detection_from_before_arrival_is_ignored() -> None:
    r = Rig(TALK)
    r.d.start_search(0.0, 0.0)
    stale = TargetEstimate(0.0, WORK_TILT_DEFAULT, 0.0, 0.0, 0.0, -1.0)
    r.run(2.0, lambda t, rig: stale)
    assert r.d.status.mode != TRACKING


def test_exhausted_search_goes_home_and_rescans() -> None:
    r = Rig(TALK)
    r.d.home = (deg(10), deg(-3))
    r.d.start_search(0.0, 0.0)
    t = r.run(90.0, nobody)
    assert r.d.status.mode == WAITING
    home = [c.value for _, c in r.log if c.kind == "abs"][-2:]
    assert home == [deg(10), deg(-3)]
    before = len(r.log)
    r.run(RESCAN_AFTER + 1.0, nobody, t0=t)
    assert len(r.log) > before, "po 60 s skan startuje ponownie"


def tracked(r: Rig, pan: float, v_pan: float, seconds: float) -> float:
    """Śledzi stojący/idący cel przez chwilę, potem cel znika."""
    return r.run(seconds, lambda t, rig: TargetEstimate(pan + v_pan * t, 0.0, v_pan, 0.0, t, t))


def test_lost_at_edge_while_walking_catches_up() -> None:
    r = Rig(PRESENTATION)
    last_pan = 0.45 * r.view().hfov
    t = r.run(0.5, lambda t, rig: TargetEstimate(last_pan, 0.0, deg(15), 0.0, t, t))
    r.log.clear()
    r.run(1.0, nobody, t0=t)
    pan = [c.value for _, c in r.log if c.kind == "abs" and c.axis == "pan"]
    assert pan and abs(pan[0] - (last_pan + deg(15))) < deg(1)


def test_rozmowa_does_not_catch_up_but_waits_at_last_azimuth() -> None:
    """Sesja 20260923-020939: w chwili utraty prędkość filtra była bezwartościowa (luki
    w detekcji), więc doganianie strzelało 54-61° za daleko, powtarzało się, a dopiero
    powrót na ostatni azymut trafiał w osobę. W rozmowie od razu ostatni azymut."""
    r = Rig(TALK)
    last_pan = 0.45 * r.view().hfov
    t = r.run(1.0, lambda t, rig: TargetEstimate(last_pan, 0.0, deg(15), 0.0, t, t))
    r.log.clear()
    r.run(10.0, nobody, t0=t)
    pans = [c.value for _, c in r.log if c.kind == "abs" and c.axis == "pan"]
    assert pans == [last_pan], pans


def test_lost_in_middle_goes_to_last_azimuth_then_zooms_out_later() -> None:
    r = Rig(TALK, zoom=1000.0)
    t = tracked(r, 0.0, 0.0, 1.0)
    r.log.clear()
    t = r.run(1.0, nobody, t0=t)
    kinds = [(c.kind, c.axis) for _, c in r.log]
    assert ("abs", "pan") in kinds and ("zoom", "zoom") not in kinds, "krótka utrata nie oddala"
    r.run(TALK.ladder_step_time + 1.0, nobody, t0=t)
    assert [c.value for _, c in r.log if c.kind == "zoom"] == [0.0]


def test_reacquire_with_auto_zoom_does_not_restore_old_zoom() -> None:
    r = Rig(TALK, zoom=800.0)
    r.d.auto_zoom = True
    t = tracked(r, 0.0, 0.0, 1.0)
    t = r.run(6.0, nobody, t0=t)
    r.log.clear()
    r.run(2.0, visible_at(0.0, 0.0), t0=t)
    assert r.d.status.mode == TRACKING
    assert [c.value for _, c in r.log if c.kind == "zoom"] == []


def test_rozmowa_stops_at_step_two() -> None:
    r = Rig(TALK)
    t = tracked(r, 0.0, 0.0, 1.0)
    r.log.clear()
    r.run(60.0, nobody, t0=t)
    assert len([c for _, c in r.log if c.kind == "abs"]) == 2
    assert r.d.status.ladder == 2


def test_prezentacja_runs_local_search_then_goes_home() -> None:
    r = Rig(PRESENTATION)
    r.d.home = (deg(5), 0.0)
    t = tracked(r, 0.0, 0.0, 1.0)
    r.log.clear()
    r.run(30.0, nobody, t0=t)
    pans = [c.value for _, c in r.log if c.kind == "abs" and c.axis == "pan"]
    hfov = r.view().hfov
    assert pans[-4:] == [0.0, hfov, -hfov, deg(5)]
    assert r.d.status.mode == WAITING and r.d.status.ladder == 4


def test_local_search_without_home_returns_to_last_azimuth() -> None:
    """Sesja 20260923-004030: bez presetu "dom" kamera została w ostatnim punkcie skanu
    lokalnego (-72° od miejsca utraty) i patrzyła w ścianę."""
    r = Rig(PRESENTATION)
    t = tracked(r, deg(28), 0.0, 1.0)
    r.log.clear()
    r.run(30.0, nobody, t0=t)
    pans = [c.value for _, c in r.log if c.kind == "abs" and c.axis == "pan"]
    hfov = r.view().hfov
    assert pans[-4:] == [deg(28), deg(28) + hfov, deg(28) - hfov, deg(28)], pans
    assert r.d.status.mode == WAITING


def test_waiting_after_local_search_rescans() -> None:
    r = Rig(PRESENTATION)
    t = tracked(r, deg(28), 0.0, 1.0)
    t = r.run(30.0, nobody, t0=t)
    before = len(r.log)
    r.run(RESCAN_AFTER + 1.0, nobody, t0=t)
    assert len(r.log) > before, "czekanie po szukaniu lokalnym musi kiedyś znów szukać"


def test_person_returning_is_reacquired() -> None:
    r = Rig(TALK, zoom=800.0)
    t = tracked(r, 0.0, 0.0, 1.0)
    # Oddalenie przychodzi po dojeździe na ostatni azymut + ladder_step_time (przy
    # zmierzonej dynamice tiltu: 5,0 s) - czekamy dłużej, żeby było co przywracać.
    t = r.run(6.0, nobody, t0=t)
    r.log.clear()
    r.run(2.0, visible_at(0.0, 0.0), t0=t)
    assert r.d.status.mode == TRACKING
    assert [c.value for _, c in r.log if c.kind == "zoom"] == [800.0]


def test_reset_clears_search() -> None:
    r = Rig(TALK)
    r.d.start_search(0.0, 0.0)
    r.d.reset()
    assert r.d.status.mode == WAITING
    r.run(1.0, nobody)
    assert r.log == []


def test_state_values_are_english_codes() -> None:
    assert (TRACKING, SEARCHING, LOST, WAITING) == ("tracking", "searching", "lost", "waiting")
    assert (IDLE, ALERT, MOVING, FOLLOWING, BRAKING) == ("idle", "alert", "moving", "following", "braking")


def test_status_notes_are_messages_with_catalog_keys() -> None:
    rig = Rig(TALK)
    rig.d.start_search(0.0)
    seen, t0 = [], 0.0
    for _ in range(8):
        t0 = rig.run(1.0, nobody, t0)
        seen.append(rig.d.status.note)
    notes = [n for n in seen if n is not None]
    assert notes, "a running search must leave a note"
    assert all(isinstance(n, Message) and n.key.startswith("director.note.") for n in notes)


if __name__ == "__main__":
    run(globals(), "Reżyser: szukanie i utrata celu")
