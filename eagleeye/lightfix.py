"""One-shot subject light correction: a tone curve computed from the face, applied as a LUT.

The camera has no host-controllable exposure (measured 2026-10-01), so the correction is a
256-entry lookup table on the luma plane. It is computed once, on request, from the skin
pixels of the person's face; nothing here runs per frame except the table lookup in vcam.py.
Constants are measurement calibration and live here, not in config.json.
"""

from __future__ import annotations

import io
import math
import warnings
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image

from .detectors import Detection
from .i18n import Message, msg
from .perception import HEAD_KEYPOINTS, KEYPOINT_MIN_CONF, head_point, pick

TARGET_SKIN = 118.0           # median skin luma to aim for
DEAD_ZONE = 25.0              # |median - target| within this: the face is already well lit
MAX_GAIN = 3.5                # steepest slope of the table: bounds noise and banding in deep shadows
GAMMA_MIN = 0.4
GAMMA_MAX = 2.5
WHITE_ANCHOR_POWER = 4.0      # shape of the ramp that puts white back at 255 (highlights only)
MEDIAN_CLIP = (8.0, 247.0)
ROI_SCALE = 1.3
ROI_MIN_SIDE_FRACTION = 1.0 / 6.0     # of the frame height (120 px at 720p)
MIN_SKIN_FRACTION = 0.0005            # of the frame area (about 460 px at 1280x720)
CR_RANGE = (133, 173)                 # standard YCrCb skin range
CB_RANGE = (77, 127)
PREVIEW_JPEG_QUALITY = 90             # JPEG quality when a corrected preview frame is re-encoded

OK = "ok"
WELL_LIT = "well_lit"
NO_FRAME = "no_frame"
NO_PERSON = "no_person"
NO_FACE = "no_face"
NO_SKIN = "no_skin"
FAILED = "failed"


@dataclass(frozen=True)
class LightResult:
    status: str
    lut: np.ndarray | None = None        # 256 x uint8, only for OK
    skin_before: float | None = None     # median skin luma of the raw frame
    skin_after: float | None = None      # the same median after the table


def face_roi(det: Detection, frame_w: int, frame_h: int) -> tuple[int, int, int, int] | None:
    """Square around the visible head keypoints, clipped to the frame; None without head keypoints."""
    points = [(x, y) for x, y, c in (det.keypoints or ())[:HEAD_KEYPOINTS] if c > KEYPOINT_MIN_CONF]
    if not points:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    cx, cy = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0
    side = max(max(xs) - min(xs), max(ys) - min(ys), frame_h * ROI_MIN_SIDE_FRACTION) * ROI_SCALE
    x0, y0 = int(max(0.0, cx - side / 2.0)), int(max(0.0, cy - side / 2.0))
    x1, y1 = int(min(float(frame_w), cx + side / 2.0)), int(min(float(frame_h), cy + side / 2.0))
    if x1 - x0 < 2 or y1 - y0 < 2:
        return None
    return x0, y0, x1, y1


def skin_luma(frame_bgr: np.ndarray, roi: tuple[int, int, int, int]) -> np.ndarray:
    """Luma values of the skin-coloured pixels inside ``roi``. The chroma mask leaves out hair,
    glasses and the chair, which otherwise drag the median down (measured)."""
    x0, y0, x1, y1 = roi
    ycc = cv2.cvtColor(frame_bgr[y0:y1, x0:x1], cv2.COLOR_BGR2YCrCb)
    cr, cb = ycc[..., 1], ycc[..., 2]
    mask = (cr >= CR_RANGE[0]) & (cr <= CR_RANGE[1]) & (cb >= CB_RANGE[0]) & (cb <= CB_RANGE[1])
    return ycc[..., 0][mask]


def build_lut(median: float) -> np.ndarray:
    """Tone table that moves a face of median luma ``median`` towards ``TARGET_SKIN``.

    Gamma curve, slope-limited, then white put back at 255 by a ramp that acts on highlights only
    (a linear ramp would also brighten the background)."""
    m = float(np.clip(median, *MEDIAN_CLIP))
    gamma = float(np.clip(math.log(TARGET_SKIN / 255.0) / math.log(m / 255.0), GAMMA_MIN, GAMMA_MAX))
    x = np.arange(256, dtype=np.float64)
    curve = 255.0 * (x / 255.0) ** gamma
    curve = np.concatenate(([0.0], np.cumsum(np.clip(np.diff(curve), 0.0, MAX_GAIN))))
    curve += (255.0 - curve[-1]) * (x / 255.0) ** WHITE_ANCHOR_POWER
    return np.clip(np.rint(curve), 0, 255).astype(np.uint8)


def choose_person(dets: list[Detection], frame_w: int, frame_h: int,
                  prefer_point: tuple[float, float] | None = None) -> Detection | None:
    """The person nearest ``prefer_point`` (the user's selection), else the largest."""
    if not dets:
        return None
    if prefer_point is not None:
        return min(dets, key=lambda d: math.dist(head_point(d), prefer_point))
    return pick(dets, None, frame_w, frame_h)


def analyse(frame_bgr: np.ndarray, dets: list[Detection],
            prefer_point: tuple[float, float] | None = None) -> LightResult:
    """Measure the face in ``frame_bgr`` (a raw, uncorrected frame) and build the table."""
    h, w = frame_bgr.shape[:2]
    person = choose_person(dets, w, h, prefer_point)
    if person is None:
        return LightResult(NO_PERSON)
    roi = face_roi(person, w, h)
    if roi is None:
        return LightResult(NO_FACE)
    skin = skin_luma(frame_bgr, roi)
    if skin.size < MIN_SKIN_FRACTION * w * h:
        return LightResult(NO_SKIN)
    median = float(np.clip(np.median(skin), *MEDIAN_CLIP))
    if abs(median - TARGET_SKIN) <= DEAD_ZONE:
        return LightResult(WELL_LIT, skin_before=median)
    lut = build_lut(median)
    return LightResult(OK, lut, median, float(lut[int(round(median))]))


def status_message(result: LightResult) -> Message:
    """The user-facing outcome. Every key is a literal so the catalog test sees it."""
    return {
        OK: msg("light.ok", before=round(result.skin_before or 0), after=round(result.skin_after or 0)),
        WELL_LIT: msg("light.well_lit"),
        NO_FRAME: msg("light.no_frame"),
        NO_PERSON: msg("light.no_person"),
        NO_FACE: msg("light.no_face"),
        NO_SKIN: msg("light.no_skin"),
        FAILED: msg("light.failed"),
    }[result.status]


def correct_jpeg(jpg: bytes, lut: np.ndarray, quality: int = PREVIEW_JPEG_QUALITY) -> bytes | None:
    """The in-app preview shows raw JPEG bytes, so a correction there is decode, table, encode.
    Works on the luma plane only (JPEG is YCbCr, as in ``vcam.jpeg_to_i420``). None on a bad JPEG."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with Image.open(io.BytesIO(jpg)) as image:
                image.draft("YCbCr", image.size)
                ycc = np.array(image if image.mode == "YCbCr" else image.convert("YCbCr"))
        ycc[..., 0] = cv2.LUT(ycc[..., 0], lut)
        out = io.BytesIO()
        Image.frombytes("YCbCr", (ycc.shape[1], ycc.shape[0]), ycc.tobytes()).save(out, "JPEG", quality=quality)
        return out.getvalue()
    except Exception:
        return None
