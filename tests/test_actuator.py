#!/usr/bin/env python3
"""Actuator: writes to the camera, the "same value" workaround, the velocity watchdog.

    .venv/bin/python tests/test_actuator.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fakes import FakeControls  # noqa: E402
from runner import run  # noqa: E402

from eagleeye.actuator import Actuator  # noqa: E402
from eagleeye.director import Command  # noqa: E402
from eagleeye.head_model import HeadModel  # noqa: E402
from eagleeye.v4l2 import (CID_PAN_ABSOLUTE, CID_PAN_SPEED, CID_TILT_SPEED,  # noqa: E402
                           CID_ZOOM_ABSOLUTE, CID_ZOOM_CONTINUOUS)


def rig(**initial):
    ctl = FakeControls(**initial)
    head = HeadModel()
    return ctl, head, Actuator(ctl, head)


def test_absolute_write_is_clamped_and_reported_to_model() -> None:
    ctl, head, act = rig()
    act.move_absolute("pan", 10_000_000, t=0.0)
    assert ctl.writes_to(CID_PAN_ABSOLUTE) == [612000]
    assert head.target("pan") == 612000


def test_same_value_is_preceded_by_a_nudge() -> None:
    ctl, _, act = rig()
    act.move_absolute("pan", 5000, t=0.0)
    act.move_absolute("pan", 5000, t=1.0)
    assert ctl.writes_to(CID_PAN_ABSOLUTE) == [5000, 4999, 5000]


def test_nudge_at_minimum_goes_up() -> None:
    ctl, _, act = rig()
    act.move_absolute("pan", -612000, t=0.0)
    act.move_absolute("pan", -612000, t=1.0)
    assert ctl.writes_to(CID_PAN_ABSOLUTE) == [-612000, -611999, -612000]


def test_velocity_writes_only_the_sign_and_only_on_change() -> None:
    ctl, head, act = rig()
    act.velocity("pan", 1, t=0.0)
    act.velocity("pan", 1, t=0.1)
    act.velocity("pan", 0, t=0.2)
    assert ctl.writes_to(CID_PAN_SPEED) == [1, 0]
    assert not head.velocity_active("pan")


def test_reversal_only_stops() -> None:
    ctl, _, act = rig()
    act.velocity("pan", 1, t=0.0)
    act.velocity("pan", -1, t=0.1)
    assert ctl.writes_to(CID_PAN_SPEED) == [1, 0]


def test_absolute_move_stops_velocity_first() -> None:
    ctl, _, act = rig()
    act.velocity("pan", 1, t=0.0)
    act.move_absolute("pan", 1000, t=0.5)
    assert ctl.writes == [(CID_PAN_SPEED, 1), (CID_PAN_SPEED, 0), (CID_PAN_ABSOLUTE, 1000)]


def test_watchdog_stops_unrefreshed_velocity() -> None:
    ctl, _, act = rig()
    act.velocity("pan", 1, t=0.0)
    assert not act.check_watchdog(0.2)
    assert act.check_watchdog(0.35)
    assert ctl.writes_to(CID_PAN_SPEED) == [1, 0]


def test_refreshing_velocity_keeps_it_alive() -> None:
    ctl, _, act = rig()
    act.velocity("pan", 1, t=0.0)
    act.velocity("pan", 1, t=0.25)
    assert not act.check_watchdog(0.5)


def test_watchdog_thread_stops_motion_when_nobody_refreshes() -> None:
    ctl, _, act = rig()
    act.start_watchdog()
    try:
        act.velocity("pan", 1, t=time.monotonic())
        time.sleep(0.6)
    finally:
        act.stop_watchdog()
    assert ctl.writes_to(CID_PAN_SPEED) == [1, 0]


def test_sync_stops_leftover_motion_and_adopts_readback() -> None:
    ctl, head, act = rig(x9a0920=15, x9a0908=40000, x9a090d=1200)
    act.sync_from_device(t=0.0)
    assert ctl.writes_to(CID_PAN_SPEED) == [0] and ctl.writes_to(CID_TILT_SPEED) == [0]
    assert head.angle("pan", 0.0) == 40000 and act.zoom_value == 1200


def test_sync_stops_leftover_continuous_zoom() -> None:
    # The camera remembers continuous zoom (e.g. -1 from an old slider) and drives the optics to
    # the limit, while the ZOOM_ABSOLUTE readback stays old - the camera-head model would be wrong
    # about the field of view.
    ctl, _, act = rig(x9a090f=-1)
    act.sync_from_device(t=0.0)
    assert ctl.writes_to(CID_ZOOM_CONTINUOUS) == [0]


def test_stop_all_writes_zero_even_when_idle() -> None:
    ctl, _, act = rig()
    act.stop_all(t=0.0)
    assert ctl.writes_to(CID_PAN_SPEED) == [0] and ctl.writes_to(CID_TILT_SPEED) == [0]


def test_refresh_zoom_follows_user_changes() -> None:
    ctl, _, act = rig()
    ctl.values[CID_ZOOM_ABSOLUTE] = 3000
    act.refresh_zoom()
    assert act.zoom_value == 3000


def test_apply_dispatches_commands() -> None:
    ctl, _, act = rig()
    act.apply([Command("abs", "tilt", 3600), Command("zoom", "zoom", 500), Command("vel", "pan", -1)], t=0.0)
    assert ctl.values[CID_ZOOM_ABSOLUTE] == 500 and ctl.writes_to(CID_PAN_SPEED) == [-1]


def test_zoom_command_starts_zoom_motion() -> None:
    ctl, _, act = rig()
    act.apply([Command("zoom", "zoom", 2400)], t=0.0)
    assert ctl.values[CID_ZOOM_ABSOLUTE] == 2400 and act.zoom_model.moving(0.1)


def test_external_zoom_change_is_detected_at_rest() -> None:
    ctl, _, act = rig()
    act.apply([Command("zoom", "zoom", 2400)], t=0.0)
    ctl.values[CID_ZOOM_ABSOLUTE] = 3000                  # someone clicked a preset during the move
    assert act.refresh_zoom(t=0.1) is False, "the optics are moving - the readback is uncertain, we do not judge"
    assert act.refresh_zoom(t=10.0) is True and act.zoom_value == 3000
    assert act.refresh_zoom(t=11.0) is False, "reported once - the new value accepted"


def test_own_zoom_is_not_external() -> None:
    ctl, _, act = rig()
    act.apply([Command("zoom", "zoom", 2400)], t=0.0)
    assert act.refresh_zoom(t=10.0) is False


def test_refresh_without_time_only_reads() -> None:
    ctl, _, act = rig()
    ctl.values[CID_ZOOM_ABSOLUTE] = 1800
    assert act.refresh_zoom() is False and act.zoom_value == 1800


if __name__ == "__main__":
    run(globals(), "Actuator")
