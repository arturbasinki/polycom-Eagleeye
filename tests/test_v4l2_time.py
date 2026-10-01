#!/usr/bin/env python3
"""Frame timestamp: timeval conversion and protection against a bad clock.

    .venv/bin/python tests/test_v4l2_time.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from runner import run  # noqa: E402

from eagleeye.v4l2 import _Timeval, frame_time, timeval_seconds  # noqa: E402


def test_timeval_to_seconds() -> None:
    assert timeval_seconds(_Timeval(5, 250000)) == 5.25


def test_plausible_timestamp_is_kept() -> None:
    assert frame_time(10.0, now=10.05) == 10.0


def test_missing_timestamp_falls_back_to_now() -> None:
    assert frame_time(0.0, now=5000.0) == 5000.0


def test_timestamp_from_future_falls_back_to_now() -> None:
    assert frame_time(10.5, now=10.0) == 10.0


def test_stale_timestamp_falls_back_to_now() -> None:
    assert frame_time(7.0, now=10.0) == 10.0


if __name__ == "__main__":
    run(globals(), "Frame timestamp")
