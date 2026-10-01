#!/usr/bin/env python3
"""Director: hysteresis, dwell, framing, lead, following.

Instead of hardware: a real HeadModel to which we apply the commands right away.

    .venv/bin/python tests/test_director.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from runner import run  # noqa: E402

from eagleeye.director import Director, Limits, REFIT_DWELL, ZOOM_DWELL, ZOOM_WITH_PAN_TILT  # noqa: E402
from eagleeye.framing import GOLDEN, SHOTS, Shot, zoom_goal  # noqa: E402
from eagleeye.geometry import View, deg  # noqa: E402
from eagleeye.head_model import Dynamics, HeadModel  # noqa: E402
from eagleeye.profiles import PRESENTATION, TALK  # noqa: E402
from eagleeye.target_filter import TargetEstimate  # noqa: E402

DYN = Dynamics()
LIM = Limits(-deg(170), deg(170), -deg(30), deg(90))
VIEW = View(1280, 720)
DT = 1 / 15


def framed_tilt(_profile=None, cam_tilt: float = 0.0) -> float:
    """World angle of a head that, at the given camera tilt, lies exactly on the golden-ratio line
    (shared by the profiles - the profile parameter stays for call compatibility)."""
    return cam_tilt + (0.5 - GOLDEN) * VIEW.vfov


def est(pan: float, tilt: float, t: float, v_pan: float = 0.0, v_tilt: float = 0.0,
        yaw=None, scale=None) -> TargetEstimate:
    return TargetEstimate(pan, tilt, v_pan, v_tilt, t, t, yaw=yaw, head_scale=scale)


def apply(head: HeadModel, cmds, t: float) -> None:
    for c in cmds:
        if c.kind == "abs":
            head.command_absolute(c.axis, c.value, t)
        elif c.kind == "vel":
            head.command_velocity(c.axis, int(c.value), t)


def simulate(director: Director, head: HeadModel, seconds: float, est_fn, t0: float = 0.0):
    """Director loop; ``est_fn(t, head)`` returns an estimate or None. Returns [(t, Command)]."""
    log = []
    n = int(seconds / DT)
    for i in range(n):
        t = t0 + i * DT
        cmds = director.tick(t, est_fn(t, head), head, VIEW)
        apply(head, cmds, t)
        log += [(t, c) for c in cmds]
    return log


def test_brief_excursion_shorter_than_dwell_is_ignored() -> None:
    d, h = Director(TALK, LIM, DYN), HeadModel(DYN)
    log = simulate(d, h, 5.0, lambda t, _: est(0.3 * VIEW.hfov if 1.0 <= t < 1.5 else 0.0,
                                               framed_tilt(TALK), t))
    assert log == []


def test_sustained_offset_moves_once_exactly_to_aim() -> None:
    d, h = Director(TALK, LIM, DYN), HeadModel(DYN)
    aim = 0.3 * VIEW.hfov
    log = simulate(d, h, 6.0, lambda t, _: est(aim, framed_tilt(TALK), t))
    pans = [c for _, c in log if c.axis == "pan"]
    assert len(pans) == 1 and pans[0].kind == "abs" and abs(pans[0].value - aim) < 1e-6
    assert abs(log[0][0] - TALK.dwell) < 2 * DT


def test_tilt_frames_head_on_golden_line() -> None:
    # The head starts outside the trigger zone (deviation 0.182 vfov > 0.12 vfov) - the test
    # checks the accuracy of arriving on the golden-ratio line in one move.
    d, h = Director(TALK, LIM, DYN), HeadModel(DYN)
    log = simulate(d, h, 3.0, lambda t, _: est(0.0, 0.3 * VIEW.vfov, t))
    tilts = [c for _, c in log if c.axis == "tilt"]
    assert len(tilts) == 1
    assert abs(tilts[0].value - (0.3 * VIEW.vfov - (0.5 - GOLDEN) * VIEW.vfov)) < 1e-6


def test_tilt_frames_head_from_within_old_zone() -> None:
    # Calibration (2026-09-25): a head 3° below the golden-ratio line lay within the 0.12 vfov
    # zone (≈4.9°), so the camera never put it on the line (the first tilt command in the whole
    # session after 92 s). Today the composition band (5%) and a quiet re-fit fix this -
    # in one move, exactly onto the line (and not a zone shrunk to 2°, which chased nods).
    d, h = Director(TALK, LIM, DYN), HeadModel(DYN)
    log = simulate(d, h, 6.0, lambda t, _: est(0.0, framed_tilt(TALK) - deg(3), t))
    tilts = [c for _, c in log if c.axis == "tilt"]
    assert len(tilts) == 1, [c.value for _, c in log]
    assert abs(tilts[0].value + deg(3)) < 1e-6


def test_rest_off_point_reframes_after_refit_dwell() -> None:
    # Acceptance 2026-09-25: the user moved the chair - the head settled 10% of the width from
    # the golden-ratio point (within the 15% trigger zone); the zone alone would leave the frame
    # in that state forever (criterion 1: error ≤ 5%). A quiet re-fit after REFIT_DWELL.
    d, h = Director(TALK, LIM, DYN), HeadModel(DYN)
    offset = 0.10 * VIEW.hfov
    log = simulate(d, h, 6.0, lambda t, _: est(offset, framed_tilt(TALK), t))
    pans = [c for _, c in log if c.axis == "pan"]
    assert len(pans) == 1, [(t, c.value) for t, c in log]
    assert abs(pans[0].value - offset) < 1e-6
    assert abs(log[0][0] - REFIT_DWELL) < 2 * DT


def test_rest_inside_composition_band_never_moves() -> None:
    d, h = Director(TALK, LIM, DYN), HeadModel(DYN)
    log = simulate(d, h, 8.0, lambda t, _: est(0.04 * VIEW.hfov, framed_tilt(TALK), t))
    assert log == []


def test_brief_mid_band_excursion_does_not_refit() -> None:
    # A 10%-width excursion lasting 2 s (a gesture) - too short to count as a new
    # rest position.
    d, h = Director(TALK, LIM, DYN), HeadModel(DYN)
    log = simulate(d, h, 8.0, lambda t, _: est(0.10 * VIEW.hfov if 2.0 <= t < 4.0 else 0.0,
                                               framed_tilt(TALK), t))
    assert log == []


def test_turning_head_moves_face_to_opposite_golden_point() -> None:
    d, h = Director(TALK, LIM, DYN), HeadModel(DYN)
    tilt = framed_tilt()
    log = simulate(d, h, 6.0, lambda t, _: est(0.0, tilt, t, yaw=0.6 if t >= 1.0 else 0.0))
    pans = [(t, c.value) for t, c in log if c.axis == "pan"]
    assert len(pans) == 1, pans
    t_move, value = pans[0]
    assert abs(t_move - (1.0 + TALK.side_dwell)) < 2 * DT
    x, _ = VIEW.world_to_pixel(0.0, tilt, value, 0.0)
    assert abs(x - GOLDEN * VIEW.frame_w) < 1.0


def test_turning_head_to_other_side_is_one_pan_move() -> None:
    # Reported 2026-09-26: nose to the left -> nose to the right went through the center point
    # (two moves). It should be one move, straight to the opposite golden-ratio point.
    d, h = Director(TALK, LIM, DYN), HeadModel(DYN)
    tilt = framed_tilt()
    yaw = lambda t: 0.6 if t < 6.0 else -0.6
    log = simulate(d, h, 12.0, lambda t, _: est(0.0, tilt, t, yaw=yaw(t)))
    pans = [(t, c.value) for t, c in log if c.axis == "pan" and t >= 6.0]
    assert len(pans) == 1, pans
    x, _ = VIEW.world_to_pixel(0.0, tilt, pans[0][1], 0.0)
    assert abs(x - (1 - GOLDEN) * VIEW.frame_w) < 1.0


def test_frontal_face_stays_centered() -> None:
    d, h = Director(TALK, LIM, DYN), HeadModel(DYN)
    log = simulate(d, h, 6.0, lambda t, _: est(0.0, framed_tilt(), t, yaw=0.1))
    assert log == []


def test_no_retarget_before_60_percent_of_move() -> None:
    d, h = Director(TALK, LIM, DYN), HeadModel(DYN)
    first = 0.3 * VIEW.hfov
    moved_at: list[float] = []

    def target(t, head):
        if head.target("pan") is not None and not moved_at:
            moved_at.append(t)
        pan = first if not moved_at else 0.9 * VIEW.hfov
        return est(pan, framed_tilt(TALK), t)

    log = simulate(d, h, 6.0, target)
    pans = [(t, c) for t, c in log if c.axis == "pan"]
    assert len(pans) == 2
    t_second = pans[1][0]
    h2 = HeadModel(DYN)
    h2.command_absolute("pan", first, pans[0][0])
    assert h2.progress("pan", t_second) >= 0.6


def test_lead_in_presentation_moves_past_aim() -> None:
    d, h = Director(PRESENTATION, LIM, DYN), HeadModel(DYN)
    log = simulate(d, h, 1.0, lambda t, _: est(0.3 * VIEW.hfov, framed_tilt(PRESENTATION), t, v_pan=deg(4)))
    pans = [c for _, c in log if c.axis == "pan" and c.kind == "abs"]
    assert pans and pans[0].value > 0.3 * VIEW.hfov


def test_presentation_lead_is_bounded() -> None:
    # Session 20260926-150210: a fast chair approach close to the camera - the head at the edge,
    # the angular velocity from the filter ~60°/s, and the lead v × ~0.5 s gave pan commands
    # +110° and -110°. The lead is for a walking person: speed up to 25°/s, at most 1/4 of the frame.
    from eagleeye.director import LEAD_MAX_FOV
    d, h = Director(PRESENTATION, LIM, DYN), HeadModel(DYN)
    aim = 0.3 * VIEW.hfov
    # Velocity toward the center of the frame - no following, an absolute move with lead.
    log = simulate(d, h, 1.0, lambda t, _: est(aim, framed_tilt(), t, v_pan=-deg(60)))
    pans = [c for _, c in log if c.axis == "pan" and c.kind == "abs"]
    assert pans, log
    assert aim - LEAD_MAX_FOV * VIEW.hfov - 1e-6 <= pans[0].value < aim, [c.value for c in pans]


def test_presentation_lead_is_pan_only() -> None:
    # The vertical "velocity" is a head nod, not walking: the lead fired the tilt past the
    # target, and a second move came back (session 20260926-011024, t=191.9 s).
    d, h = Director(PRESENTATION, LIM, DYN), HeadModel(DYN)
    tilt = framed_tilt() + 0.3 * VIEW.vfov
    log = simulate(d, h, 1.0, lambda t, _: est(0.0, tilt, t, v_tilt=deg(6)))
    tilts = [c for _, c in log if c.axis == "tilt"]
    assert len(tilts) == 1 and abs(tilts[0].value - 0.3 * VIEW.vfov) < 1e-6, [c.value for c in tilts]


def test_nod_inside_tilt_zone_does_not_move() -> None:
    # A ±2.5° nod (vertical gestures in talk mode) fits within the tilt zone and returns to the
    # composition band before REFIT_DWELL elapses - the camera stands still.
    import math
    for profile in (TALK, PRESENTATION):
        d, h = Director(profile, LIM, DYN), HeadModel(DYN)
        log = simulate(d, h, 10.0, lambda t, _: est(0.0, framed_tilt() + deg(2.5) * math.sin(t * 4.0), t))
        assert log == [], (profile.name, [(t, c.axis, c.value) for t, c in log])


def test_pan_waits_for_side_decision_then_moves_once() -> None:
    # A step aside with the face turning away: the position move started before the side was
    # decided, and a side change 1-1.5 s later forced a second move (session 20260926-011024, e.g.
    # t=1248-1250 s). Pan waits for the side decision and travels once, to the new side's point.
    d, h = Director(TALK, LIM, DYN), HeadModel(DYN)
    tilt = framed_tilt()
    offset = 0.25 * VIEW.hfov
    log = simulate(d, h, 6.0, lambda t, _: est(offset if t >= 1.0 else 0.0, tilt, t,
                                               yaw=0.6 if t >= 1.0 else 0.0))
    pans = [(t, c.value) for t, c in log if c.axis == "pan"]
    assert len(pans) == 1, pans
    t_move, value = pans[0]
    assert t_move >= 1.0 + TALK.side_dwell - 2 * DT
    x, _ = VIEW.world_to_pixel(offset, tilt, value, 0.0)
    assert abs(x - GOLDEN * VIEW.frame_w) < 1.0


def test_target_near_edge_does_not_wait_for_side() -> None:
    # A target at the edge (walking) does not wait for the side - a loss would be worse than two moves.
    d, h = Director(TALK, LIM, DYN), HeadModel(DYN)
    offset = 0.42 * VIEW.hfov
    log = simulate(d, h, 2.0, lambda t, _: est(offset, framed_tilt(), t, yaw=0.6))
    pans = [t for t, c in log if c.axis == "pan"]
    assert pans and pans[0] < TALK.side_dwell


def test_target_beyond_limit_does_not_spam_moves() -> None:
    d = Director(TALK, LIM, DYN)
    h = HeadModel(DYN, pan=LIM.pan_max)
    log = simulate(d, h, 10.0, lambda t, _: est(LIM.pan_max + 0.4 * VIEW.hfov, framed_tilt(TALK), t))
    assert [c for _, c in log if c.axis == "pan"] == []


def test_fast_walker_triggers_follow_then_brake_then_absolute() -> None:
    d, h = Director(PRESENTATION, LIM, DYN), HeadModel(DYN)
    v = deg(20)
    log = simulate(d, h, 4.0, lambda t, _: est(0.12 * VIEW.hfov + v * t, framed_tilt(PRESENTATION), t, v_pan=v))
    pan = [(c.kind, c.value) for _, c in log if c.axis == "pan"]
    assert ("vel", 1) in pan
    start = pan.index(("vel", 1))
    stop = pan.index(("vel", 0), start)
    assert pan[start:stop].count(("vel", 1)) > 1, "following must refresh the command for the watchdog"
    assert any(k == "abs" for k, _ in pan[stop:]), "after braking, an absolute arrival"


def test_talk_never_uses_velocity() -> None:
    d, h = Director(TALK, LIM, DYN), HeadModel(DYN)
    log = simulate(d, h, 4.0, lambda t, _: est(0.2 * VIEW.hfov + deg(20) * t, framed_tilt(TALK), t,
                                               v_pan=deg(20)))
    assert all(c.kind != "vel" for _, c in log)


def test_tilt_never_uses_velocity() -> None:
    d, h = Director(PRESENTATION, LIM, DYN), HeadModel(DYN)
    log = simulate(d, h, 3.0, lambda t, _: est(0.0, framed_tilt(PRESENTATION) + deg(20) * t, t,
                                               v_tilt=deg(20)))
    assert all(not (c.axis == "tilt" and c.kind == "vel") for _, c in log)


def test_follow_stops_before_pan_limit() -> None:
    d = Director(PRESENTATION, LIM, DYN)
    h = HeadModel(DYN, pan=deg(150))
    v = deg(25)
    simulate(d, h, 4.0, lambda t, _: est(deg(150) + 0.12 * VIEW.hfov + v * t, framed_tilt(PRESENTATION), t, v_pan=v))
    assert max(h.angle("pan", i * 0.05) for i in range(120)) <= LIM.pan_max + deg(0.5)


ZOOM_MOVE = 1.0     # s of optics travel in the test


def run_zoom(d, h, seconds: float, est_fn, zoom: float = 0.0, t0: float = 0.0):
    """Like simulate(), but the view has the current zoom and the zoom command travels ZOOM_MOVE s."""
    log, zoom_now, until = [], zoom, -1.0
    for i in range(int(seconds / DT)):
        t = t0 + i * DT
        cmds = d.tick(t, est_fn(t, h), h, View(1280, 720, zoom_now), zoom_moving=t < until)
        apply(h, cmds, t)
        for c in cmds:
            if c.kind == "zoom":
                zoom_now, until = c.value, t + ZOOM_MOVE
        log += [(t, c) for c in cmds]
    return log, zoom_now


def auto_director(profile=TALK):
    d = Director(profile, LIM, DYN)
    d.auto_zoom = True
    return d, HeadModel(DYN)


def test_auto_zoom_moves_once_to_shot_after_dwell() -> None:
    d, h = auto_director()
    scale = deg(4)
    log, zoom = run_zoom(d, h, 8.0, lambda t, _: est(0.0, framed_tilt(), t, yaw=0.0, scale=scale))
    zooms = [(t, c.value) for t, c in log if c.kind == "zoom"]
    assert len(zooms) == 1, zooms
    assert abs(zooms[0][0] - ZOOM_DWELL) < 2 * DT
    assert abs(scale / View(1280, 720, zoom).vfov - SHOTS["MCU"]) < 0.01


def test_zoom_ignores_small_changes_and_short_lean() -> None:
    d, h = auto_director()
    z0 = zoom_goal(est(0.0, 0.0, 0.0, scale=deg(4)), Shot("MCU", SHOTS["MCU"]), View(1280, 720))

    def fn(t, _):
        s = deg(4) * (1.1 if int(t) % 2 else 1.0)          # ±10% - within the 20% band
        if 5.0 <= t < 6.5:
            s = deg(6)                                      # a 1.5 s lean < ZOOM_DWELL
        return est(0.0, framed_tilt(), t, yaw=0.0, scale=s)
    log, _ = run_zoom(d, h, 12.0, fn, zoom=z0)
    assert [c for _, c in log if c.kind == "zoom"] == []


def test_zoom_gap_jitter_does_not_reset_dwell() -> None:
    # Calibration (2026-09-25): a step back gave a target 1.15-1.25x relative to the current
    # zoom; every dip below 1.2 reset the dwell and no move ever started
    # (~11 s of variation, zero commands). The dwell resets only below ZOOM_BAND_RESET.
    d, h = auto_director()
    base = deg(4)
    z0 = zoom_goal(est(0.0, 0.0, 0.0, scale=base), Shot("MCU", SHOTS["MCU"]), View(1280, 720))

    def fn(t, _):
        m = 1.25 if int(t / 1.5) % 2 == 0 else 1.18
        return est(0.0, framed_tilt(), t, yaw=0.0, scale=base / m)
    log, _ = run_zoom(d, h, 12.0, fn, zoom=z0)
    zooms = [c for _, c in log if c.kind == "zoom"]
    assert len(zooms) == 1, [(t, c.value) for t, c in log if c.kind == "zoom"]


def test_zoom_target_jitter_around_band_does_not_move() -> None:
    # Acceptance 2026-09-25 (session 20260925-235118): at talk distance the MCU target sat
    # around 1.1-1.4x, and scale variations (gestures, head rotation) carried the ratio across
    # the 1.2x threshold - zoom "sawtooth" (13 moves in 2 min at a constant distance; the target
    # oscillated 1.16-1.38x, never dropping below the 1.15x reset). A move starts only when the
    # target is stable in the dwell window (change < ZOOM_TARGET_STABILITY).
    d, h = auto_director()
    base = deg(4)
    z0 = zoom_goal(est(0.0, 0.0, 0.0, scale=base), Shot("MCU", SHOTS["MCU"]), View(1280, 720))

    def fn(t, _):
        m = 1.38 if int(t / 1.5) % 2 == 0 else 1.18
        return est(0.0, framed_tilt(), t, yaw=0.0, scale=base / m)
    log, _ = run_zoom(d, h, 12.0, fn, zoom=z0)
    assert [c for _, c in log if c.kind == "zoom"] == []


def test_zoom_stable_target_still_moves_once() -> None:
    # Same as above, but the target jumps to 1.4x and stays there (e.g. a step back):
    # the stability gate must not block a real shot change.
    d, h = auto_director()
    base = deg(4)
    z0 = zoom_goal(est(0.0, 0.0, 0.0, scale=base), Shot("MCU", SHOTS["MCU"]), View(1280, 720))

    def fn(t, _):
        m = 1.4 if t >= 1.0 else 1.0
        return est(0.0, framed_tilt(), t, yaw=0.0, scale=base / m)
    log, _ = run_zoom(d, h, 8.0, fn, zoom=z0)
    zooms = [(t, c) for t, c in log if c.kind == "zoom"]
    assert len(zooms) == 1, zooms
    assert abs(zooms[0][0] - (1.0 + ZOOM_DWELL)) < 2 * DT


def test_auto_zoom_off_sends_no_zoom() -> None:
    d, h = Director(TALK, LIM, DYN), HeadModel(DYN)
    log, _ = run_zoom(d, h, 8.0, lambda t, _: est(0.0, framed_tilt(), t, scale=deg(4)))
    assert [c for _, c in log if c.kind == "zoom"] == []


def test_pan_tilt_aim_at_goal_zoom_when_zooming() -> None:
    d, h = auto_director()
    log, zoom = run_zoom(d, h, 8.0, lambda t, _: est(deg(3), framed_tilt(), t, yaw=0.0, scale=deg(4)))
    t_zoom = next(t for t, c in log if c.kind == "zoom")
    same_tick = [c for t, c in log if t == t_zoom and c.kind == "abs"]
    if not ZOOM_WITH_PAN_TILT:
        assert same_tick == [], "zoom sequentially: pan/tilt only after the optics move"
        return
    assert {c.axis for c in same_tick} == {"pan", "tilt"}
    pan = next(c.value for c in same_tick if c.axis == "pan")
    tilt = next(c.value for c in same_tick if c.axis == "tilt")
    x, y = View(1280, 720, zoom).world_to_pixel(deg(3), framed_tilt(), pan, tilt)
    assert abs(x - 640) < 1.0 and abs(y - GOLDEN * 720) < 1.0


if __name__ == "__main__":
    run(globals(), "Director: tracking")
