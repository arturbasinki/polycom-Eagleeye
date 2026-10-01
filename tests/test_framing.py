#!/usr/bin/env python3
"""Composition: golden ratio, side from face direction, zoom from the shot.

    .venv/bin/python tests/test_framing.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from runner import run  # noqa: E402

from eagleeye.framing import (AUTO_ZOOM_MAX, CENTER, GOLDEN, LEFT, RIGHT, SHOTS,  # noqa: E402
                              Shot, SideSelector, aim, zoom_goal)
from eagleeye.geometry import View, deg  # noqa: E402
from eagleeye.profiles import PRESENTATION, TALK, resolve  # noqa: E402
from eagleeye.target_filter import TargetEstimate  # noqa: E402

VIEW = View(1280, 720)
MCU = Shot("MCU", SHOTS["MCU"])
P = {"enter": 0.35, "exit_": 0.20, "dwell": 1.5}


def e(pan: float = 0.0, tilt: float = 0.0, yaw=None, scale=None) -> TargetEstimate:
    return TargetEstimate(pan, tilt, 0.0, 0.0, 0.0, 0.0, yaw=yaw, head_scale=scale)


def feed(sel: SideSelector, yaw_fn, t0: float, t1: float) -> str:
    """Steps every 0.1 s from t0 to t1 (excluding t1); time counted from integers - no drift."""
    for i in range(round(t0 * 10), round(t1 * 10)):
        t = i / 10
        sel.update(t, yaw_fn(t), **P)
    return sel.side


# --- aim point -----------------------------------------------------------

def test_center_side_keeps_face_centered_on_golden_line() -> None:
    pan, tilt = aim(e(deg(10), deg(5)), CENTER, VIEW)
    x, y = VIEW.world_to_pixel(deg(10), deg(5), pan, tilt)
    assert abs(x - 640) < 1e-6 and abs(y - GOLDEN * 720) < 1e-6


def test_left_side_puts_face_on_left_golden_point() -> None:
    pan, tilt = aim(e(), LEFT, VIEW)
    x, y = VIEW.world_to_pixel(0.0, 0.0, pan, tilt)
    assert abs(x - GOLDEN * 1280) < 1e-6 and abs(y - GOLDEN * 720) < 1e-6


def test_right_side_with_inverted_axes_is_still_image_based() -> None:
    inv = View(1280, 720, 0, invert_pan=True, invert_tilt=True)
    pan, tilt = aim(e(), RIGHT, inv)
    x, y = inv.world_to_pixel(0.0, 0.0, pan, tilt)
    assert abs(x - (1 - GOLDEN) * 1280) < 1e-6 and abs(y - GOLDEN * 720) < 1e-6


def test_aim_uses_field_of_view_of_given_zoom() -> None:
    zoomed = View(1280, 720, 2400)
    pan, _ = aim(e(), LEFT, zoomed)
    x, _ = zoomed.world_to_pixel(0.0, 0.0, pan, 0.0)
    assert abs(x - GOLDEN * 1280) < 1e-6


# --- zoom from the shot -------------------------------------------------------------

def test_zoom_goal_fills_frame_by_shot() -> None:
    scale = deg(4)
    z = zoom_goal(e(scale=scale), MCU, VIEW)
    assert abs(scale / View(1280, 720, z).vfov - SHOTS["MCU"]) < 0.01


def test_zoom_goal_is_clamped_and_needs_scale() -> None:
    assert zoom_goal(e(scale=deg(30)), MCU, VIEW) == 0.0, "too close - widest"
    assert zoom_goal(e(scale=deg(0.5)), MCU, VIEW) == AUTO_ZOOM_MAX, "too far - limit"
    assert zoom_goal(e(scale=None), MCU, VIEW) is None


def test_zoom_goal_does_not_depend_on_current_zoom() -> None:
    a = zoom_goal(e(scale=deg(4)), MCU, VIEW)
    b = zoom_goal(e(scale=deg(4)), MCU, View(1280, 720, 3000))
    assert abs(a - b) < 1e-6


# --- side -------------------------------------------------------------------

def test_sustained_turn_right_moves_face_to_left_point() -> None:
    s = SideSelector()
    assert feed(s, lambda t: 0.6, 0.0, 1.4) == CENTER
    assert feed(s, lambda t: 0.6, 1.4, 1.7) == LEFT


def test_sustained_turn_left_moves_face_to_right_point() -> None:
    s = SideSelector()
    assert feed(s, lambda t: -0.6, 0.0, 1.7) == RIGHT


def test_short_glance_does_not_change_side() -> None:
    s = SideSelector()
    assert feed(s, lambda t: 0.6 if t < 1.0 else 0.0, 0.0, 5.0) == CENTER


def test_yaw_flicker_across_enter_threshold_keeps_center() -> None:
    s = SideSelector()
    assert feed(s, lambda t: 0.40 if round(t * 10) % 2 else 0.30, 0.0, 10.0) == CENTER


def test_hysteresis_between_thresholds_keeps_side() -> None:
    s = SideSelector()
    feed(s, lambda t: 0.6, 0.0, 1.7)
    assert feed(s, lambda t: 0.27, 1.7, 7.0) == LEFT, "0.20 < |yaw| < 0.35 - no change"
    assert feed(s, lambda t: 0.10, 7.0, 8.7) == CENTER


def test_left_to_right_switches_directly() -> None:
    # Reported 2026-09-26: a left -> right transition through the center gave two camera moves
    # (first to the center, then to the other point). A look over the shoulder is guarded against
    # by the side_dwell dwell, not by a stop at the center.
    s = SideSelector()
    feed(s, lambda t: 0.6, 0.0, 1.7)
    sides = []
    t = 1.7
    while t < 3.5:
        sides.append(s.update(t, -0.6, 0.35, 0.20, 1.5))
        t += 1 / 15
    assert CENTER not in sides, sides
    assert sides[-1] == RIGHT


def test_head_turn_sweeping_through_frontal_goes_straight_to_other_side() -> None:
    # A head turn from left to right passes through a face-on pose (yaw ~ 0) - briefly.
    s = SideSelector()
    feed(s, lambda t: 0.6, 0.0, 1.7)
    yaw = lambda t: 0.6 - 1.2 * min(max((t - 1.7) / 0.5, 0.0), 1.0)   # +0.6 -> -0.6 in 0.5 s
    sides = []
    t = 1.7
    while t < 4.0:
        sides.append(s.update(t, yaw(t), 0.35, 0.20, 1.5))
        t += 1 / 15
    assert CENTER not in sides, sides
    assert sides[-1] == RIGHT


def test_short_look_over_shoulder_keeps_side() -> None:
    s = SideSelector()
    feed(s, lambda t: 0.6, 0.0, 1.7)
    assert feed(s, lambda t: -0.6 if t < 2.7 else 0.6, 1.7, 6.0) == LEFT


def test_sustained_frontal_face_returns_to_center() -> None:
    s = SideSelector()
    feed(s, lambda t: 0.6, 0.0, 1.7)
    assert feed(s, lambda t: 0.05, 1.7, 3.4) == CENTER


def test_missing_yaw_keeps_side() -> None:
    s = SideSelector()
    feed(s, lambda t: 0.6, 0.0, 1.7)
    assert feed(s, lambda t: None, 1.7, 7.0) == LEFT


def test_reset_returns_to_center() -> None:
    s = SideSelector()
    feed(s, lambda t: 0.6, 0.0, 1.7)
    s.reset()
    assert s.side == CENTER


def test_profiles_have_shots_and_overrides_are_validated() -> None:
    assert TALK.shot == "MCU" and PRESENTATION.shot == "MS"
    assert resolve("talk", {"shot": "CU"}).shot == "CU"
    assert resolve("talk", {"shot": "bzdura"}).shot == "MCU"
    assert resolve("talk", {"side_dwell": "2.5"}).side_dwell == 2.5


def test_side_values_are_english_codes() -> None:
    assert (CENTER, LEFT, RIGHT) == ("center", "left", "right")


if __name__ == "__main__":
    run(globals(), "Frame composition")
