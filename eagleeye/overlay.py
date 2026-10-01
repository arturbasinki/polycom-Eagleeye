"""Drawing on the preview: detections, their head points, the target's head point, the
golden-ratio lines with their intersections and the highlighted point the camera frames
the head on.

No trigger-zone rectangle: that is the director's internal threshold, not composition - the
frame is judged by whether the head point lies on the golden-ratio point.

Detections are computed on a frame reduced by half, while the preview may be full
resolution - the coordinates are scaled by ``state.frame_size``.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .framing import GOLDEN
from .i18n import Message, msg, t
from .identity import SELECTED, SUSPENDED
from .tracker import TrackerState

COLOR_DET = (160, 160, 160)
COLOR_TARGET = (80, 220, 80)
COLOR_HEAD = (255, 180, 60)
COLOR_GRID = (40, 200, 240)      # gold: the golden-ratio lines and points
COLOR_AIM = (60, 60, 255)        # red: the point the camera frames the head on
COLOR_SELECTED = (255, 100, 230)   # pink: the person selected by clicking
COLOR_SUSPENDED = (0, 165, 255)    # orange: the selected person, temporarily not visible
HEAD_KEYPOINTS = 5          # COCO: nose, eyes, ears - the head point is computed from them
KEYPOINT_MIN_CONF = 0.3


def _hex(bgr: tuple[int, int, int]) -> str:
    b, g, r = bgr
    return f"#{r:02x}{g:02x}{b:02x}"


@dataclass(frozen=True)
class Shape:
    """Overlay primitive in window coordinates: ``rect`` (outline), ``dot`` (disc),
    ``ring`` (ring) or ``line`` (segment from (x, y) to (x2, y2))."""
    kind: str
    x: float
    y: float
    w: float = 0.0
    h: float = 0.0
    r: float = 0.0
    color: str = ""
    stroke: float = 1.0
    label: str = ""
    x2: float = 0.0
    y2: float = 0.0


def golden_points() -> list[tuple[float, float]]:
    """The four intersection points of the golden-ratio lines (frame fractions)."""
    return [(gx, gy) for gy in (GOLDEN, 1.0 - GOLDEN) for gx in (GOLDEN, 1.0 - GOLDEN)]


def _fit(box_w: float, box_h: float, sw: int, sh: int) -> tuple[float, float, float]:
    """Scale and offset (ox, oy) of an image fitted into the box, top-aligned and centered."""
    k = min(box_w / sw, box_h / sh)
    return k, (box_w - sw * k) / 2, 0.0


def frame_point(box_w: float, box_h: float, frame_size: tuple[int, int],
                x: float, y: float) -> tuple[float, float] | None:
    """Window point (e.g. a click) -> frame point; ``None`` when it falls outside the image
    (bands on the sides) or the box/frame has no size. The inverse of the ``overlay_shapes`` geometry."""
    sw, sh = frame_size
    if sw <= 0 or sh <= 0 or box_w <= 0 or box_h <= 0:
        return None
    k, ox, oy = _fit(box_w, box_h, sw, sh)
    fx, fy = (x - ox) / k, (y - oy) / k
    return (fx, fy) if 0 <= fx < sw and 0 <= fy < sh else None


def selection_text(state: TrackerState) -> Message | None:
    """One-line description of the person selection for the window (a message, or None)."""
    if state.selection == SELECTED:
        return msg("selection.selected", id=state.selected_id)
    if state.selection == SUSPENDED:
        return msg("selection.suspended", seconds=f"{state.selection_left:.0f}")
    return state.selection_note


def _selection_shapes(state: TrackerState, k: float, ox: float, oy: float) -> list[Shape]:
    info = next((i for i in state.tracks if i.id == state.selected_id), None)
    if info is None or state.selection not in (SELECTED, SUSPENDED):
        return []
    x, y, w, h = info.box
    if state.selection == SUSPENDED:
        return [Shape("rect", ox + x * k, oy + y * k, w * k, h * k, color=_hex(COLOR_SUSPENDED),
                      stroke=3, label=t("overlay.searching", seconds=f"{state.selection_left:.0f}"))]
    return [Shape("rect", ox + x * k, oy + y * k, w * k, h * k, color=_hex(COLOR_SELECTED),
                  stroke=4, label=t("overlay.following", id=info.id))]


def overlay_shapes(state: TrackerState, box_w: float, box_h: float) -> list[Shape]:
    """The same as :func:`annotate`, but as shapes to draw over the image.

    The image in the window is fitted (``BoxFit.CONTAIN``) into the ``box_w`` x ``box_h`` box
    and aligned to the top edge, horizontally to the center - like ``Alignment.TOP_CENTER``
    of the preview in app.py. This way the preview gets the camera frame unchanged.
    """
    sw, sh = state.frame_size
    if not state.enabled or sw <= 0 or sh <= 0 or box_w <= 0 or box_h <= 0:
        return []
    k, ox, oy = _fit(box_w, box_h, sw, sh)
    iw, ih = sw * k, sh * k
    det_color, head_color = _hex(COLOR_DET), _hex(COLOR_HEAD)
    shapes: list[Shape] = []
    for d in state.detections:
        x, y, w, h = d.as_box()
        shapes.append(Shape("rect", ox + x * k, oy + y * k, w * k, h * k, color=det_color,
                            stroke=2, label=f"{d.label} {d.score:.2f}"))
        for px, py, conf in (d.keypoints or ())[:HEAD_KEYPOINTS]:
            if conf > KEYPOINT_MIN_CONF:
                shapes.append(Shape("dot", ox + px * k, oy + py * k, r=4, color=head_color))
    shapes += _selection_shapes(state, k, ox, oy)
    if state.target is not None:
        shapes.append(Shape("dot", ox + state.target.x * k, oy + state.target.y * k, r=8,
                            color=_hex(COLOR_TARGET)))
    grid = _hex(COLOR_GRID)
    for g in (GOLDEN, 1.0 - GOLDEN):
        shapes.append(Shape("line", ox + g * iw, oy, x2=ox + g * iw, y2=oy + ih, color=grid, stroke=1.5))
        shapes.append(Shape("line", ox, oy + g * ih, x2=ox + iw, y2=oy + g * ih, color=grid, stroke=1.5))
    for gx, gy in golden_points():
        shapes.append(Shape("ring", ox + gx * iw, oy + gy * ih, r=5, color=grid, stroke=2.5))
    ax, ay = state.aim
    aim = _hex(COLOR_AIM)
    shapes.append(Shape("ring", ox + ax * iw, oy + ay * ih, r=14, color=aim, stroke=3))
    shapes.append(Shape("dot", ox + ax * iw, oy + ay * ih, r=5, color=aim))
    return shapes


def annotate(frame_bgr: np.ndarray, state: TrackerState) -> np.ndarray:
    if not state.enabled:
        return frame_bgr
    fh, fw = frame_bgr.shape[:2]
    sw, sh = state.frame_size
    k = fw / sw if sw else 1.0
    for d in state.detections:
        x, y, w, h = (int(v * k) for v in d.as_box())
        cv2.rectangle(frame_bgr, (x, y), (x + w, y + h), COLOR_DET, 2)
        cv2.putText(frame_bgr, f"{d.label} {d.score:.2f}", (x, max(12, y - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, COLOR_DET, 1, cv2.LINE_AA)
        for px, py, conf in (d.keypoints or ())[:HEAD_KEYPOINTS]:
            if conf > KEYPOINT_MIN_CONF:
                cv2.circle(frame_bgr, (int(px * k), int(py * k)), 4, COLOR_HEAD, -1)
    if state.target is not None:
        cv2.circle(frame_bgr, (int(state.target.x * k), int(state.target.y * k)), 8, COLOR_TARGET, -1)
    for g in (GOLDEN, 1.0 - GOLDEN):
        cv2.line(frame_bgr, (int(g * fw), 0), (int(g * fw), fh), COLOR_GRID, 2)
        cv2.line(frame_bgr, (0, int(g * fh)), (fw, int(g * fh)), COLOR_GRID, 2)
    for gx, gy in golden_points():
        cv2.circle(frame_bgr, (int(gx * fw), int(gy * fh)), 5, COLOR_GRID, 2, cv2.LINE_AA)
    ax, ay = state.aim
    cx, cy = int(ax * fw), int(ay * fh)
    cv2.circle(frame_bgr, (cx, cy), 14, COLOR_AIM, 3, cv2.LINE_AA)
    cv2.circle(frame_bgr, (cx, cy), 5, COLOR_AIM, -1, cv2.LINE_AA)
    return frame_bgr
