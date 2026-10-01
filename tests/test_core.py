#!/usr/bin/env python3
"""Core: head scale in world angles, measurements paused while the zoom moves.

    .venv/bin/python tests/test_core.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fakes import FakeControls  # noqa: E402
from runner import run  # noqa: E402

from eagleeye.core import TrackingCore  # noqa: E402
from eagleeye.director import LOST, Command  # noqa: E402
from eagleeye.head_model import Dynamics  # noqa: E402
from eagleeye.perception import Observation  # noqa: E402
from eagleeye.profiles import TALK  # noqa: E402

W, H = 960, 540
DYN = Dynamics(zoom_latency=0.1, zoom_base=0.3, zoom_speed=2000.0)


def obs(t: float, scale: float | None = 60.0, yaw: float | None = 0.0) -> Observation:
    return Observation(480.0, 206.0, t, 0.9, "pose", (0, 0, 10, 10), yaw=yaw, head_scale_px=scale)


def core() -> TrackingCore:
    c = TrackingCore(FakeControls(), TALK, DYN)
    c.actuator.sync_from_device(0.0)
    return c


def test_head_scale_enters_filter_in_world_units() -> None:
    c = core()
    c.step(0.0, obs(0.0, scale=60.0), W, H)
    est = c.last_estimate
    assert abs(est.head_scale - 60.0 * c.view(W, H).arcsec_per_px) < 1e-6 and est.yaw == 0.0


def test_frames_during_zoom_motion_are_skipped() -> None:
    c = core()
    c.actuator.apply([Command("zoom", "zoom", 2400)], 0.0)     # travels to 0.1 + 0.3 + 1.2 = 1.6 s
    c.step(0.5, obs(0.5), W, H)
    assert c.last_world is None
    c.step(3.0, obs(3.0), W, H)
    assert c.last_world is not None


def test_target_is_held_while_zoom_moves() -> None:
    c = core()
    c.step(0.0, obs(0.0), W, H)
    c.actuator.apply([Command("zoom", "zoom", 2400)], 0.1)
    c.step(1.0, None, W, H)                 # 1 s without a measurement > lost_after (0.4 s)
    assert c.last_estimate is not None and c.director.status.mode != LOST


if __name__ == "__main__":
    run(globals(), "Tracking core")
