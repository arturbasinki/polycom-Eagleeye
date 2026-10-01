#!/usr/bin/env python3
"""Light correction maths: face ROI, skin luma, tone table, one-shot analysis.

    .venv/bin/python tests/test_lightfix.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fakes import face_scene  # noqa: E402
from runner import run  # noqa: E402

from eagleeye import i18n, lightfix  # noqa: E402
from eagleeye.detectors import Detection  # noqa: E402
from eagleeye.lightfix import (FAILED, MAX_GAIN, NO_FACE, NO_FRAME, NO_PERSON, NO_SKIN, OK,  # noqa: E402
                               WELL_LIT, LightResult, analyse, build_lut, choose_person, face_roi,
                               status_message)


def test_dark_face_gets_a_lifting_curve() -> None:
    frame, det = face_scene(40)
    result = analyse(frame, [det])
    assert result.status == OK and result.lut is not None
    assert abs(result.skin_before - 40) <= 2
    assert result.lut[40] >= 70, result.lut[40]
    assert result.skin_after > result.skin_before + 30


def test_bright_face_gets_a_darkening_curve() -> None:
    frame, det = face_scene(200)
    result = analyse(frame, [det])
    assert result.status == OK and result.lut[200] <= 160, result.lut[200]


def test_face_inside_the_dead_zone_is_left_alone() -> None:
    frame, det = face_scene(120)
    result = analyse(frame, [det])
    assert result.status == WELL_LIT and result.lut is None


def test_lut_is_anchored_monotonic_and_gain_limited() -> None:
    for median in (10, 26, 60, 167, 240):
        lut = build_lut(median)
        steps = np.diff(lut.astype(int))
        assert lut.dtype == np.uint8 and lut.shape == (256,)
        assert lut[0] == 0 and lut[255] == 255, (median, lut[0], lut[255])
        assert (steps >= 0).all(), median
        assert steps.max() <= MAX_GAIN + 1, (median, steps.max())


def test_no_person_no_face_no_skin() -> None:
    frame, det = face_scene(40)
    assert analyse(frame, []).status == NO_PERSON
    blind = Detection(det.x, det.y, det.w, det.h, 0.9, "pose", ((0.0, 0.0, 0.0),) * 17)
    assert analyse(frame, [blind]).status == NO_FACE
    boxed = Detection(det.x, det.y, det.w, det.h, 0.9, "pose", None)
    assert analyse(frame, [boxed]).status == NO_FACE
    grey = np.full(frame.shape, 150, np.uint8)
    assert analyse(grey, [det]).status == NO_SKIN


def test_hair_and_background_do_not_move_the_median() -> None:
    frame, det = face_scene(40)
    h, w = frame.shape[:2]
    cy = h // 2
    frame[cy - 53:cy - 30, :] = 0                       # a black band across the top of the ROI (hair)
    result = analyse(frame, [det])
    assert result.status == OK and abs(result.skin_before - 40) <= 2, result.skin_before


def test_selected_point_beats_the_bigger_person() -> None:
    big = Detection(0, 100, 200, 300, 0.9, "pose")        # head point (100, 100)
    small = Detection(375, 120, 50, 80, 0.9, "pose")      # head point (400, 120)
    assert choose_person([big, small], 640, 360) is big
    assert choose_person([big, small], 640, 360, prefer_point=(395.0, 118.0)) is small
    assert choose_person([], 640, 360, prefer_point=(1.0, 1.0)) is None


def test_face_roi_is_clipped_to_the_frame() -> None:
    corner = Detection(0, 0, 40, 80, 0.9, "pose", ((5.0, 5.0, 0.9), (12.0, 3.0, 0.9)) + ((0.0, 0.0, 0.0),) * 15)
    x0, y0, x1, y1 = face_roi(corner, 640, 360)
    assert x0 == 0 and y0 == 0 and 0 < x1 <= 640 and 0 < y1 <= 360
    far = Detection(600, 330, 40, 30, 0.9, "pose", ((639.0, 359.0, 0.9),) + ((0.0, 0.0, 0.0),) * 16)
    x0, y0, x1, y1 = face_roi(far, 640, 360)
    assert x1 == 640 and y1 == 360 and x1 - x0 >= 2 and y1 - y0 >= 2


def test_result_does_not_depend_on_frame_resolution() -> None:
    results = []
    for w, h in ((320, 180), (640, 360), (1280, 720)):
        frame, det = face_scene(40, w, h)
        results.append(analyse(frame, [det]))
    assert all(r.status == OK for r in results), [r.status for r in results]
    medians = [r.skin_before for r in results]
    assert max(medians) - min(medians) <= 2, medians
    assert all(abs(int(r.lut[40]) - int(results[0].lut[40])) <= 2 for r in results)


def test_status_messages_exist_in_the_catalog() -> None:
    i18n.set_language("en")
    ok = status_message(LightResult(OK, skin_before=26.0, skin_after=66.0)).text("en")
    assert "26" in ok and "66" in ok, ok
    for status in (WELL_LIT, NO_FRAME, NO_PERSON, NO_FACE, NO_SKIN, FAILED):
        text = status_message(LightResult(status)).text("en")
        assert not text.startswith("light."), (status, text)


if __name__ == "__main__":
    run(globals(), "Light correction")
