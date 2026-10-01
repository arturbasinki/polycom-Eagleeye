#!/usr/bin/env python3
"""ControlDevice after close: a V4L2Error, not a ValueError from fcntl.

Clicking "Connect" again in the app closed the old controls before the
tracker stopped; its stop() wrote to fd=-1 and raised a ValueError that nobody
caught (the guards catch V4L2Error).

    .venv/bin/python tests/test_v4l2_closed.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from runner import run  # noqa: E402

from eagleeye.v4l2 import CID_PAN_SPEED, ControlDevice, V4L2Error  # noqa: E402


def closed_device() -> ControlDevice:
    dev = ControlDevice("/dev/null")
    dev.close()
    return dev


def test_set_on_closed_device_raises_v4l2_error() -> None:
    try:
        closed_device().set(CID_PAN_SPEED, 0)
    except V4L2Error:
        return
    raise AssertionError("expected V4L2Error")


def test_get_on_closed_device_raises_v4l2_error() -> None:
    try:
        closed_device().get(CID_PAN_SPEED)
    except V4L2Error:
        return
    raise AssertionError("expected V4L2Error")


def test_tracker_stop_survives_closed_controls() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from test_tracker import make  # noqa: E402
    from fakes import FakeControls  # noqa: E402

    ctl = FakeControls()
    tr = make(controls=ctl)
    tr.controls = tr.core.actuator.controls = closed_device()
    tr.stop()       # must not raise


if __name__ == "__main__":
    run(globals(), "Closed device")
