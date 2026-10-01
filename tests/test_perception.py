#!/usr/bin/env python3
"""Perception: the head point from the pose (RTMO-s), target choice, half-scale decoding.

    .venv/bin/python tests/test_perception.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from runner import run  # noqa: E402

from eagleeye.detectors import Detection, decode_mjpeg_scaled  # noqa: E402
from eagleeye.perception import (Perception, face_yaw, head_point,  # noqa: E402
                                 head_scale_px, pick)

HIDDEN = (0.0, 0.0, 0.05)
FRAME = np.zeros((540, 960, 3), np.uint8)


def person(x: int, y: int, w: int, h: int, head: dict[int, tuple[float, float]], score: float = 0.9) -> Detection:
    """Person with COCO keypoints: in ``head`` index -> (x, y) of visible points (0 nose, 1-2 eyes, 3-4 ears)."""
    kps = [HIDDEN] * 17
    for i, (px, py) in head.items():
        kps[i] = (px, py, 0.9)
    kps[5] = (x + w * 0.7, y + h * 0.25, 0.9)      # shoulders - they are not head points
    kps[6] = (x + w * 0.3, y + h * 0.25, 0.9)
    return Detection(x, y, w, h, score, "poza", tuple(kps))


FRONTAL = person(300, 80, 200, 460, {0: (400, 150), 1: (410, 140), 2: (390, 140), 3: (425, 145), 4: (375, 145)})


class FakePose:
    name = "poza"
    backend = "atrapa"

    def __init__(self, dets: list[Detection]) -> None:
        self.dets = dets
        self.last_ms = 2.5

    def detect(self, frame_bgr) -> list[Detection]:
        return list(self.dets)


def test_head_point_is_mean_of_visible_head_keypoints() -> None:
    assert head_point(FRONTAL) == (400.0, 144.0)


def test_profile_uses_only_visible_points() -> None:
    profile = person(300, 80, 200, 460, {0: (380, 150), 2: (390, 140), 4: (405, 145)})
    x, y = head_point(profile)
    assert abs(x - (380 + 390 + 405) / 3) < 1e-9 and y == 145.0


def test_back_view_uses_ears() -> None:
    back = person(300, 80, 200, 460, {3: (425, 145), 4: (375, 145)})
    assert head_point(back) == (400.0, 145.0)


def test_no_visible_head_points_means_top_of_box() -> None:
    """Head above the frame (a standing person close to the camera): the point sits on the top edge - the camera moves up."""
    headless = person(300, 0, 200, 540, {})
    assert head_point(headless) == (400.0, 0.0)


def test_shoulders_are_not_head_points() -> None:
    only_shoulders = person(300, 80, 200, 460, {})
    assert head_point(only_shoulders) == (400.0, 80.0)


def test_without_previous_the_largest_person_wins() -> None:
    small = person(10, 10, 50, 120, {0: (35, 30)})
    assert pick([small, FRONTAL], None, 960, 540) is FRONTAL


def test_previous_position_keeps_the_same_person() -> None:
    near = person(700, 60, 120, 300, {0: (760, 100)})
    far_bigger = person(50, 40, 300, 500, {0: (200, 120)})
    assert pick([far_bigger, near], (755.0, 105.0), 960, 540) is near


def test_observe_returns_head_of_target_and_all_detections() -> None:
    p = Perception(FakePose([FRONTAL]))
    obs, dets = p.observe(FRAME, t=12.5, previous=None)
    assert (obs.x, obs.y, obs.t, obs.source) == (400.0, 144.0, 12.5, "poza")
    assert dets == [FRONTAL] and p.last_ms == 2.5 and "atrapa" in p.description


def test_observe_without_detections_returns_none() -> None:
    obs, dets = Perception(FakePose([])).observe(FRAME, t=0.0, previous=None)
    assert obs is None and dets == []


def test_scaled_decode_halves_the_frame() -> None:
    img = np.random.default_rng(1).integers(0, 255, (720, 1280, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    assert decode_mjpeg_scaled(buf.tobytes(), 2).shape == (360, 640, 3)


def test_scaled_decode_of_garbage_is_none() -> None:
    assert decode_mjpeg_scaled(b"not a jpeg") is None


def test_frontal_face_has_zero_yaw() -> None:
    assert abs(face_yaw(FRONTAL)) < 0.05


def test_face_turned_right_in_image_has_positive_yaw() -> None:
    turned = person(300, 80, 200, 460, {0: (418, 150), 1: (415, 140), 2: (395, 140),
                                         3: (425, 145), 4: (378, 145)})
    assert face_yaw(turned) > 0.35


def test_face_turned_left_in_image_has_negative_yaw() -> None:
    turned = person(300, 80, 200, 460, {0: (382, 150), 1: (405, 140), 2: (385, 140),
                                         3: (422, 145), 4: (375, 145)})
    assert face_yaw(turned) < -0.35


def test_profile_yaw_is_clamped_to_one() -> None:
    profile = person(300, 80, 200, 460, {0: (430, 150), 1: (420, 140), 2: (405, 140), 4: (385, 145)})
    assert face_yaw(profile) == 1.0


def test_yaw_needs_nose_and_two_side_points() -> None:
    back = person(300, 80, 200, 460, {3: (425, 145), 4: (375, 145)})
    assert face_yaw(back) is None
    one_eye = person(300, 80, 200, 460, {0: (400, 150), 1: (410, 140)})
    assert face_yaw(one_eye) is None


def test_head_scale_is_eyes_to_shoulders() -> None:
    # FRONTAL: eyes y=140, shoulders y = 80 + 460 * 0.25 = 195
    assert abs(head_scale_px(FRONTAL) - 55.0) < 1e-6


def test_head_scale_without_shoulders_is_none() -> None:
    # Acceptance 2026-09-25: the emergency eyes→shoulders ratio (EYE_TO_SHOULDER) cannot be
    # calibrated - the ratio depends on head rotation (3.1 face-on, 5.3 in profile), and
    # switching sources when the shoulders flicker jumped 1.8x and pumped the zoom.
    # Without shoulders - None; the filter keeps the last scale (test_missing_..._keep_previous).
    kps = list(FRONTAL.keypoints)
    kps[5] = kps[6] = HIDDEN
    det = Detection(300, 80, 200, 460, 0.9, "poza", tuple(kps))
    assert head_scale_px(det) is None


def test_head_scale_without_eyes_is_none() -> None:
    back = person(300, 80, 200, 460, {3: (425, 145), 4: (375, 145)})
    assert head_scale_px(back) is None


def test_observation_from_a_chosen_detection() -> None:
    """Person pointed at by a click: the same observation as from pick(), only from the chosen detection."""
    obs = Perception(FakePose([])).observation(FRONTAL, 3.5)
    assert (obs.x, obs.y, obs.t, obs.source, obs.box) == (400.0, 144.0, 3.5, "poza", FRONTAL.as_box())
    assert abs(obs.yaw) < 0.05 and abs(obs.head_scale_px - 55.0) < 1e-6


def test_observe_fills_yaw_and_scale() -> None:
    obs, _ = Perception(FakePose([FRONTAL])).observe(FRAME, 1.0, None)
    assert abs(obs.yaw) < 0.05 and abs(obs.head_scale_px - 55.0) < 1e-6


if __name__ == "__main__":
    run(globals(), "Perception")
