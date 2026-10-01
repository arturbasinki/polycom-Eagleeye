#!/usr/bin/env python3
"""Tracking profiles and the scan-point planner.

    .venv/bin/python tests/test_profiles_search.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from runner import run  # noqa: E402

from eagleeye.geometry import deg  # noqa: E402
from eagleeye.profiles import DEFAULT_PROFILE, PRESENTATION, PROFILES, TALK, resolve  # noqa: E402
from eagleeye.search import local_plan, pan_sequence, startup_plan  # noqa: E402

PAN = (-deg(170), deg(170))
TILT = (-deg(30), deg(90))


def test_profiles_match_spec() -> None:
    assert (TALK.trigger_pan, TALK.dwell, TALK.follow, TALK.ladder_max) == (0.15, 0.8, False, 2)
    assert (PRESENTATION.trigger_pan, PRESENTATION.dwell, PRESENTATION.follow, PRESENTATION.ladder_max) == (0.26, 0.2, True, 4)


def test_resolve_applies_only_tunable_overrides() -> None:
    p = resolve("presentation", {"dwell": 0.5, "follow": False, "nonsense": 3})
    assert p.dwell == 0.5 and p.follow is True


def test_unknown_profile_falls_back_to_talk() -> None:
    assert resolve("???").name == "talk"


def test_profile_names_are_english_and_default_is_talk() -> None:
    assert set(PROFILES) == {"talk", "presentation"} and DEFAULT_PROFILE == "talk"
    assert TALK.name == "talk" and PRESENTATION.name == "presentation"
    assert resolve("rozmowa").name == "talk", "unknown names fall back to the default profile"    # polish: deliberate


def test_pan_sequence_sweeps_one_side_then_the_other() -> None:
    assert pan_sequence(0.0, *PAN) == [0.0, deg(60), deg(120), deg(170), -deg(60), -deg(120), -deg(170)]


def test_pan_sequence_sweeps_toward_larger_range_first() -> None:
    seq = pan_sequence(deg(100), *PAN)
    assert seq == [deg(100), deg(40), -deg(20), -deg(80), -deg(140), deg(160)]


def test_pan_sequence_clamps_start() -> None:
    seq = pan_sequence(deg(500), *PAN)
    assert seq[0] == deg(170) and seq[-1] == -deg(170) and len(seq) == 7


def test_startup_plan_has_second_row_higher() -> None:
    plan = startup_plan(0.0, -deg(5), PAN, TILT)
    tilts = sorted({t for _, t in plan})
    assert tilts == [-deg(5), deg(15)] and len(plan) == 14      # the second row reaches a standing person's head


def test_local_plan_is_three_points_around_center() -> None:
    plan = local_plan(0.0, 0.0, deg(72), PAN)
    assert [p for p, _ in plan] == [0.0, deg(72), -deg(72)]


def test_local_plan_near_limit_drops_duplicates() -> None:
    plan = local_plan(deg(165), 0.0, deg(72), PAN)
    assert [p for p, _ in plan] == [deg(165), deg(170), deg(93)]


if __name__ == "__main__":
    run(globals(), "Profiles and scan")
