"""Perception: from a frame, the target head point (Observation) and the detection list for
the preview.

The source is a single pose model (RTMO-s): 17 COCO keypoints for each person.
The head point is the mean of the visible nose, eye and ear keypoints - it exists
from the front, in profile, standing and from behind. Previously the face (YuNet) and the body
(YOLOX) were two sources, and switching between them shifted the target
by 9-13° when standing up, sitting down and turning around (spike 2026-09-23;
RTMO-s at the same moments at most 3-5°).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .detectors import Detection, PoseDetector

HEAD_KEYPOINTS = 5          # COCO: 0 nose, 1-2 eyes, 3-4 ears
KEYPOINT_MIN_CONF = 0.3     # rule from the spike measurements
# Penalty scale for distance from the previous target (fraction of the frame diagonal).
ASSOCIATION_SCALE = 0.15


@dataclass(frozen=True)
class Observation:
    x: float                          # head point in frame pixels
    y: float
    t: float                          # frame capture time (CLOCK_MONOTONIC)
    score: float
    source: str                       # "pose"
    box: tuple[int, int, int, int]
    yaw: float | None = None          # face direction: + nose to the right in the image (framing)
    head_scale_px: float | None = None  # eye→shoulder segment in frame pixels


def head_point(det: Detection) -> tuple[float, float]:
    """Mean of the visible head keypoints; when none is visible - the center of the top edge
    of the box (head above the frame for a person standing close to the camera: the camera
    must move up)."""
    if det.keypoints:
        pts = [(x, y) for x, y, c in det.keypoints[:HEAD_KEYPOINTS] if c > KEYPOINT_MIN_CONF]
        if pts:
            return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
    return det.x + det.w / 2.0, float(det.y)


def _visible(det: Detection, indices: tuple[int, ...]) -> list[tuple[float, float]]:
    kps = det.keypoints or ()
    return [(kps[i][0], kps[i][1]) for i in indices if i < len(kps) and kps[i][2] > KEYPOINT_MIN_CONF]


def face_yaw(det: Detection) -> float | None:
    """Head-turn indicator in [-1, 1]: position of the nose relative to the center of the visible eyes
    and ears, in halves of their spread. Positive = nose to the right in the image (face turned
    to the right of the frame). A proportion within the face - it does not depend on distance
    or zoom."""
    nose = _visible(det, (0,))
    sides = _visible(det, (1, 2, 3, 4))
    if not nose or len(sides) < 2:
        return None
    lo = min(p[0] for p in sides)
    hi = max(p[0] for p in sides)
    half = (hi - lo) / 2.0
    if half < 1.0:
        return None
    return max(-1.0, min(1.0, (nose[0][0] - (lo + hi) / 2.0) / half))


def head_scale_px(det: Detection) -> float | None:
    """Head scale: the vertical segment eye line -> shoulder line (px). Without visible shoulders
    - None (we do not estimate from the eye distance: the eye→shoulder ratio depends on head rotation,
    2026-09-25, so switching sources would pump the zoom); the filter holds the last
    measure."""
    eyes = _visible(det, (1, 2))
    shoulders = _visible(det, (5, 6))
    if eyes and shoulders:
        eye_y = sum(p[1] for p in eyes) / len(eyes)
        shoulder_y = sum(p[1] for p in shoulders) / len(shoulders)
        return abs(shoulder_y - eye_y)
    return None


def pick(cands: list[Detection], previous: tuple[float, float] | None,
         frame_w: int, frame_h: int) -> Detection | None:
    """Without a previous target: the largest person (closest). With one: size
    with an exponential penalty for distance - the target does not jump to another person."""
    if not cands:
        return None
    if previous is None:
        return max(cands, key=lambda d: d.area)
    scale = ASSOCIATION_SCALE * math.hypot(frame_w, frame_h)
    return max(cands, key=lambda d: d.area * math.exp(-math.dist(head_point(d), previous) / scale))


class Perception:
    def __init__(self, pose_detector) -> None:
        self.pose = pose_detector
        self.last_ms = 0.0

    @property
    def description(self) -> str:
        return f"{self.pose.name}: {self.pose.backend}"

    def detect(self, frame_bgr) -> list[Detection]:
        """Everyone in ``frame_bgr``, with no target selection - for one-off use outside the tracking loop."""
        return self.pose.detect(frame_bgr)

    def observe(self, frame_bgr, t: float,
                previous: tuple[float, float] | None) -> tuple[Observation | None, list[Detection]]:
        dets = self.pose.detect(frame_bgr)
        self.last_ms = getattr(self.pose, "last_ms", 0.0)
        h, w = frame_bgr.shape[:2]
        target = pick(dets, previous, w, h)
        if target is None:
            return None, dets
        return self.observation(target, t), dets

    @staticmethod
    def observation(det: Detection, t: float) -> Observation:
        """Observation from the chosen detection (head, face turn, scale) - shared by ``pick``
        and by the person selected by a click (eagleeye.identity)."""
        x, y = head_point(det)
        return Observation(x, y, t, det.score, det.label, det.as_box(),
                           yaw=face_yaw(det), head_scale_px=head_scale_px(det))


def default_perception(use_gpu: bool) -> Perception:
    return Perception(PoseDetector(prefer_gpu=use_gpu))
