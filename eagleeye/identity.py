"""Person identity across frames: tracks in world angles + clothing colour.

RTMO-s returns a list of people in each frame with no memory. ``PersonTracker`` gives them
stable numbers, and ``TargetSelection`` keeps track of which one the user selected.

Tracks live in world angles (arcsec, ``View.pixel_to_world``), not in pixels:
the camera moves, while a standing person has a fixed position in the world. We measure
distances in body heights of the person (box size in arcsec), so the thresholds do not
depend on zoom or on the distance from the camera.

Appearance is the HSV histogram of the torso (between the shoulders and hips from the
COCO keypoints). The clothing colour decides crossings and recovery after a loss;
without a new model.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

import cv2
import numpy as np

from .detectors import Detection
from .i18n import Message, msg
from .perception import KEYPOINT_MIN_CONF, head_point

ToWorld = Callable[[float, float], tuple[float, float]]

# Position gate (in body heights): constant part + growth with absence time.
GATE_BASE = 0.6
GATE_SPEED = 1.0                 # ~walking: 0.8 body heights per second
GATE_MAX = 3.0
SIZE_MAX = 0.7                   # |ln(detection size / track size)|
APP_NEUTRAL = 0.35               # appearance cost when there is no histogram
APP_MAX_NEAR = 0.6               # Bhattacharyya threshold just after a loss...
APP_MAX_FAR = 0.4                # ...and after APP_FAR_S seconds of absence
APP_FAR_S = 3.0
APP_WEIGHT = 1.0
SIZE_WEIGHT = 0.5
AMBIGUITY = 0.1                  # taking over a suspended track requires this APPEARANCE advantage
PREDICT_MAX_S = 0.5              # we do not extrapolate velocity any longer
ALPHA, BETA = 0.6, 0.3           # position alpha-beta filter
RETAIN_S = 1.5                   # how long a track lives without a detection (except a protected one)
HIST_MIX = 0.15                  # share of the new frame in the averaged histogram
HIST_BINS = (6, 3, 3)            # H, S, V
MIN_ROI = 6                      # px; a smaller crop = no histogram


@dataclass
class Track:
    id: int
    pan: float                   # head point in the world [arcsec]
    tilt: float
    size: float                  # box height in the world [arcsec]
    last_seen: float
    v_pan: float = 0.0
    v_tilt: float = 0.0
    hist: np.ndarray | None = None
    det: Detection | None = None     # detection matched in THIS frame; None = track suspended
    head_px: tuple[float, float] = (0.0, 0.0)     # last known head and box (frame px)
    box: tuple[int, int, int, int] = (0, 0, 0, 0)
    misses: int = 0


@dataclass(frozen=True)
class TrackInfo:
    """Immutable snapshot of the track for the UI (TrackerState)."""
    id: int
    box: tuple[int, int, int, int]      # last known box (for a suspended one - from the last frame)
    head: tuple[float, float]
    visible: bool


def torso_hist(frame_bgr: np.ndarray, det: Detection) -> np.ndarray | None:
    """Normalised HSV histogram of the torso or None when it cannot be cropped."""
    fh, fw = frame_bgr.shape[:2]
    kps = det.keypoints or ()

    def pts(idx):
        return [(kps[i][0], kps[i][1]) for i in idx if i < len(kps) and kps[i][2] > KEYPOINT_MIN_CONF]

    shoulders, hips = pts((5, 6)), pts((11, 12))
    if len(shoulders) == 2:
        x0 = min(p[0] for p in shoulders)
        x1 = max(p[0] for p in shoulders)
        y0 = sum(p[1] for p in shoulders) / 2.0
        if hips:
            y1 = sum(p[1] for p in hips) / len(hips)
        else:
            y1 = y0 + 1.2 * (x1 - x0)
    else:                            # without shoulders: a strip below the head, centre of the box
        x0, x1 = det.x + 0.2 * det.w, det.x + 0.8 * det.w
        y0, y1 = det.y + 0.15 * det.h, det.y + 0.55 * det.h
    # we pull the area towards the centre - the edges catch the background
    mx, my = 0.2 * (x1 - x0), 0.15 * (y1 - y0)
    xa, xb = int(max(0, x0 + mx)), int(min(fw, x1 - mx))
    ya, yb = int(max(0, y0 + my)), int(min(fh, y1 - my))
    if xb - xa < MIN_ROI or yb - ya < MIN_ROI:
        return None
    hsv = cv2.cvtColor(frame_bgr[ya:yb, xa:xb], cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1, 2], None, list(HIST_BINS), [0, 180, 0, 256, 0, 256])
    total = float(hist.sum())
    if total <= 0:
        return None
    return (hist / total).astype(np.float32).ravel()


def _bhattacharyya(a: np.ndarray, b: np.ndarray) -> float:
    return float(cv2.compareHist(a, b, cv2.HISTCMP_BHATTACHARYYA))


class PersonTracker:
    def __init__(self) -> None:
        self.tracks: dict[int, Track] = {}
        self._next_id = 1

    def reset(self) -> None:
        self.tracks.clear()

    def update(self, dets: list[Detection], frame_bgr: np.ndarray, t: float, to_world: ToWorld,
               protect: int | None = None, protect_s: float = 0.0) -> list[Track]:
        """Assigns detections to tracks; returns all live ones (visible and suspended).

        ``protect``/``protect_s``: the track selected by the user lives without a detection
        for up to ``protect_s`` seconds (the rest - ``RETAIN_S``)."""
        meas = []
        for d in dets:
            hx, hy = head_point(d)
            pan, tilt = to_world(hx, hy)
            cx = d.x + d.w / 2.0
            size = abs(to_world(cx, d.y)[1] - to_world(cx, d.y + d.h)[1])
            meas.append((d, pan, tilt, max(size, 1.0), torso_hist(frame_bgr, d), (hx, hy)))
        tracks = list(self.tracks.values())
        cost: dict[tuple[int, int], float] = {}
        looks: dict[tuple[int, int], float] = {}     # just the appearance cost of those pairs
        for ti, tr in enumerate(tracks):
            gap = max(0.0, t - tr.last_seen)
            dt = min(gap, PREDICT_MAX_S)
            ppan, ptilt = tr.pan + tr.v_pan * dt, tr.tilt + tr.v_tilt * dt
            gate = min(GATE_MAX, GATE_BASE + GATE_SPEED * gap)
            app_max = APP_MAX_NEAR + (APP_MAX_FAR - APP_MAX_NEAR) * min(1.0, gap / APP_FAR_S)
            for di, (d, pan, tilt, size, hist, _) in enumerate(meas):
                dist = math.hypot(pan - ppan, tilt - ptilt) / max(tr.size, 1.0)
                if dist > gate:
                    continue
                c_size = abs(math.log(size / max(tr.size, 1.0)))
                if c_size > SIZE_MAX:
                    continue
                if tr.hist is not None and hist is not None:
                    c_app = _bhattacharyya(tr.hist, hist)
                    if c_app > app_max:
                        continue
                else:
                    c_app = APP_NEUTRAL
                cost[(ti, di)] = dist + SIZE_WEIGHT * c_size + APP_WEIGHT * c_app
                looks[(ti, di)] = c_app
        used_t: set[int] = set()
        used_d: set[int] = set()
        matched: dict[int, int] = {}
        for (ti, di), c in sorted(cost.items(), key=lambda kv: kv[1]):
            if ti in used_t or di in used_d:
                continue
            if tracks[ti].misses > 0 and self._ambiguous(looks, ti, di):
                continue
            used_t.add(ti)
            used_d.add(di)
            matched[ti] = di
        for ti, tr in enumerate(tracks):
            if ti in matched:
                self._update_track(tr, meas[matched[ti]], t)
            else:
                tr.det = None
                tr.misses += 1
        for di, m in enumerate(meas):
            if di not in used_d:
                self._spawn(m, t)
        for tid in [tid for tid, tr in self.tracks.items()
                    if tr.det is None and t - tr.last_seen > (protect_s if tid == protect else RETAIN_S)]:
            del self.tracks[tid]
        return list(self.tracks.values())

    @staticmethod
    def _ambiguous(looks, ti: int, di: int) -> bool:
        """A suspended track is taken over only with a clear appearance advantage of the rival.
        After a few seconds position weighs little (the gate grows), so distance cannot
        decide between two people in similar clothes."""
        mine = looks[(ti, di)]
        return any((t2, d2) != (ti, di) and (t2 == ti or d2 == di) and abs(c2 - mine) < AMBIGUITY
                   for (t2, d2), c2 in looks.items())

    def _update_track(self, tr: Track, m, t: float) -> None:
        det, pan, tilt, size, hist, head_px = m
        gap = max(t - tr.last_seen, 1e-3)
        dt = min(gap, PREDICT_MAX_S)
        ppan, ptilt = tr.pan + tr.v_pan * dt, tr.tilt + tr.v_tilt * dt
        r_pan, r_tilt = pan - ppan, tilt - ptilt
        tr.pan, tr.tilt = ppan + ALPHA * r_pan, ptilt + ALPHA * r_tilt
        if gap <= PREDICT_MAX_S:
            tr.v_pan += BETA * r_pan / gap
            tr.v_tilt += BETA * r_tilt / gap
        else:
            tr.v_pan = tr.v_tilt = 0.0
        tr.size = 0.7 * tr.size + 0.3 * size
        if hist is not None:
            tr.hist = hist if tr.hist is None else (1 - HIST_MIX) * tr.hist + HIST_MIX * hist
        tr.det, tr.head_px, tr.box, tr.last_seen, tr.misses = det, head_px, det.as_box(), t, 0

    def _spawn(self, m, t: float) -> None:
        det, pan, tilt, size, hist, head_px = m
        self.tracks[self._next_id] = Track(self._next_id, pan, tilt, size, t, hist=hist,
                                           det=det, head_px=head_px, box=det.as_box())
        self._next_id += 1


def track_infos(tracks: list[Track]) -> tuple[TrackInfo, ...]:
    return tuple(TrackInfo(tr.id, tr.box, tr.head_px, tr.det is not None) for tr in tracks)


def track_at(infos: tuple[TrackInfo, ...], x: float, y: float) -> int | None:
    """ID of the visible person under the frame point; with overlapping boxes - the one with the closer head."""
    best, best_d = None, math.inf
    for info in infos:
        bx, by, bw, bh = info.box
        if info.visible and bx <= x <= bx + bw and by <= y <= by + bh:
            d = math.hypot(x - info.head[0], y - info.head[1])
            if d < best_d:
                best, best_d = info.id, d
    return best


AUTO, SELECTED, SUSPENDED = "auto", "selected", "suspended"
GAP_S = 0.5                      # this long without a detection the selected one stays "visible"


class TargetSelection:
    """User selection: AUTO -> SELECTED <-> SUSPENDED -> AUTO after ``hold_s``."""

    def __init__(self, hold_s: float = 6.0) -> None:
        self.hold_s = hold_s
        self.state = AUTO
        self.track_id: int | None = None
        self.event: Message | None = None
        self._seen = 0.0

    def select(self, track_id: int, t: float) -> None:
        self.state, self.track_id, self.event, self._seen = SELECTED, track_id, None, t

    def clear(self) -> None:
        self.state, self.track_id, self.event = AUTO, None, None

    def remaining(self, t: float) -> float:
        if self.state != SUSPENDED:
            return 0.0
        return max(0.0, self.hold_s - (t - self._seen))

    def resolve(self, tracks: list[Track], t: float) -> Track | None:
        """The selected person's track when visible; otherwise None. Changes state."""
        if self.state == AUTO:
            return None
        tr = next((x for x in tracks if x.id == self.track_id), None)
        if tr is not None and tr.det is not None:
            self.state, self._seen = SELECTED, t
            return tr
        gap = t - self._seen
        if gap > self.hold_s:
            self.state, self.track_id = AUTO, None
            self.event = msg("identity.selection_lost")
        elif gap > GAP_S:
            self.state = SUSPENDED
        return None
