#!/usr/bin/env python3
"""Camera-head model: predicting the real angle from the command history.

    .venv/bin/python tests/test_head_model.py
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from runner import run  # noqa: E402

from eagleeye.head_model import (Dynamics, HeadModel, ZoomModel, dynamics_from_settings,  # noqa: E402
                                 velocity_displacement, velocity_stop_elapsed)
from eagleeye.geometry import deg  # noqa: E402
from eagleeye.motion import s_curve  # noqa: E402

DYN = Dynamics()


def test_s_curve_endpoints_and_monotonic() -> None:
    values = [s_curve(i / 10) for i in range(11)]
    assert values[0] == 0.0 and values[-1] == 1.0
    assert all(b > a for a, b in zip(values, values[1:]))


def test_absolute_move_waits_for_latency_then_reaches_target() -> None:
    h = HeadModel(DYN)
    h.command_absolute("pan", 36000, t=10.0)
    end = 10.0 + DYN.abs_latency + DYN.abs_duration(36000)
    assert abs(h.angle("pan", 10.0 + DYN.abs_latency)) < 1e-6
    assert h.angle("pan", end) == 36000
    assert h.moving("pan", end - 0.01) and not h.moving("pan", end)
    assert h.target("pan") == 36000


def test_absolute_move_is_monotonic() -> None:
    h = HeadModel(DYN)
    h.command_absolute("tilt", -18000, t=0.0)
    samples = [h.angle("tilt", i * 0.05) for i in range(40)]
    assert all(b <= a for a, b in zip(samples, samples[1:]))


def test_new_command_starts_from_predicted_position() -> None:
    h = HeadModel(DYN)
    h.command_absolute("pan", 36000, t=0.0)
    mid = DYN.abs_latency + DYN.abs_duration(36000) / 2
    here = h.angle("pan", mid)
    h.command_absolute("pan", 0, t=mid)
    assert abs(h.angle("pan", mid) - here) < 1e-6


def test_progress_runs_from_zero_to_one() -> None:
    h = HeadModel(DYN)
    h.command_absolute("pan", 36000, t=0.0)
    assert h.progress("pan", 0.0) == 0.0
    assert h.progress("pan", 100.0) == 1.0


def test_velocity_waits_for_latency_then_cruises() -> None:
    assert velocity_displacement(DYN, DYN.vel_latency, None) == 0.0
    t1 = DYN.vel_latency + DYN.vel_ramp + 0.5
    slope = (velocity_displacement(DYN, t1 + 0.1, None) - velocity_displacement(DYN, t1, None)) / 0.1
    assert abs(slope - DYN.vel_speed) < 1e-6


def test_coast_after_stop_matches_coast_distance() -> None:
    coast = velocity_displacement(DYN, math.inf, 2.0) - velocity_displacement(DYN, 2.0, None)
    assert abs(coast - DYN.coast_distance()) < 1.0


def test_rest_angle_while_driving_includes_coast() -> None:
    h = HeadModel(DYN)
    h.command_velocity("pan", 1, t=0.0)
    assert h.velocity_active("pan") and h.velocity_direction("pan") == 1
    assert abs(h.rest_angle("pan", 2.0) - (h.angle("pan", 2.0) + DYN.coast_distance())) < 1.0


def test_stopped_velocity_axis_comes_to_rest() -> None:
    h = HeadModel(DYN)
    h.command_velocity("pan", 1, t=0.0)
    h.command_velocity("pan", 0, t=1.0)
    end = velocity_stop_elapsed(DYN, 1.0)
    assert not h.velocity_active("pan")
    assert h.moving("pan", end - 0.01) and not h.moving("pan", end + 0.001)
    assert h.angle("pan", end + 1.0) == h.angle("pan", end + 5.0)


def test_negative_direction_moves_left() -> None:
    h = HeadModel(DYN)
    h.command_velocity("pan", -1, t=0.0)
    assert h.angle("pan", 1.0) < 0


def test_velocity_marks_position_inexact_until_absolute_move() -> None:
    h = HeadModel(DYN)
    h.command_velocity("pan", 1, t=0.0)
    assert not h.exact("pan")
    h.command_velocity("pan", 0, t=0.5)
    h.command_absolute("pan", 0, t=2.0)
    assert h.exact("pan")


def test_tilt_has_its_own_trajectory() -> None:
    # Tilt is slower than pan (tools/measure_trajectory.py, 2026-09-26).
    dyn = Dynamics(tilt_abs_latency=0.10, tilt_abs_base=0.80, tilt_abs_speed=deg(66.5), tilt_abs_nu=0.7)
    h = HeadModel(dyn)
    h.command_absolute("pan", deg(10), 0.0)
    h.command_absolute("tilt", deg(10), 0.0)
    end_pan = dyn.abs_latency + dyn.abs_duration(deg(10))
    end_tilt = 0.10 + 0.80 + 10 / 66.5
    assert abs(dyn.abs_duration(deg(10), "tilt") - (0.80 + 10 / 66.5)) < 1e-9
    assert not h.moving("pan", end_pan + 0.01) and h.moving("tilt", end_pan + 0.01)
    assert not h.moving("tilt", end_tilt + 0.01)
    assert h.angle("tilt", 0.5) < h.angle("pan", 0.5)


def test_tilt_without_own_values_uses_pan() -> None:
    d = Dynamics(tilt_abs_latency=None, tilt_abs_base=None, tilt_abs_speed=None, tilt_abs_nu=None)
    assert d.abs_params("tilt") == d.abs_params("pan")


def test_calibration_is_the_default_without_config() -> None:
    # The unit calibration is in the code: a missing or lost config.json does not change it.
    assert dynamics_from_settings(None) == Dynamics()
    assert dynamics_from_settings({}) == Dynamics()
    d = Dynamics()
    assert d.abs_params("tilt") == (0.10, 0.80, 66.5 * 3600, 0.7)
    assert abs(d.abs_speed - deg(67.52)) < 1 and abs(d.vel_speed - deg(40.67)) < 1
    assert (d.zoom_latency, d.zoom_base, d.zoom_speed) == (0.142, 0.201, 3069.5)


def test_config_null_does_not_erase_calibration() -> None:
    d = dynamics_from_settings({"tilt_abs_base": None, "abs_speed": "nonsense"})
    assert d == Dynamics()


def test_dynamics_from_settings_ignores_unknown_keys() -> None:
    d = dynamics_from_settings({"vel_speed": 100000.0, "bogus": 1})
    assert d.vel_speed == 100000.0 and d.abs_speed == DYN.abs_speed


def test_zoom_model_moves_for_latency_plus_duration() -> None:
    dyn = Dynamics(zoom_latency=0.2, zoom_base=0.3, zoom_speed=2000.0)
    z = ZoomModel(dyn, 0.0)
    z.command(2400.0, t=10.0)
    end = 10.0 + 0.2 + 0.3 + 2400.0 / 2000.0
    assert z.moving(10.0) and z.moving(end - 0.01) and not z.moving(end + 0.01)
    assert z.value == 2400.0


def test_zoom_model_same_value_is_not_a_move() -> None:
    z = ZoomModel(Dynamics(), 800.0)
    z.command(800.0, t=0.0)
    assert not z.moving(0.1)


def test_zoom_model_reset_stops_motion() -> None:
    z = ZoomModel(Dynamics(), 0.0)
    z.command(3000.0, t=0.0)
    z.reset(1200.0)
    assert not z.moving(0.1) and z.value == 1200.0


def test_dynamics_from_settings_reads_zoom_fields() -> None:
    dyn = dynamics_from_settings({"zoom_speed": 1234, "zoom_latency": 0.25})
    assert dyn.zoom_speed == 1234.0 and dyn.zoom_latency == 0.25


if __name__ == "__main__":
    run(globals(), "Camera-head model")
