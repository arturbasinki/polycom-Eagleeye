"""Tożsamość osób między klatkami: ścieżki w kątach świata + kolor ubrania.

RTMO-s zwraca w każdej klatce listę osób bez pamięci. ``PersonTracker`` nadaje im
stałe numery, a ``TargetSelection`` pilnuje, którą z nich użytkownik wybrał.

Ścieżki żyją w kątach świata (arcsec, ``View.pixel_to_world``), nie w pikselach:
kamera się rusza, a stojąca osoba ma stałe położenie w świecie. Odległości mierzymy
w wysokościach ciała osoby (rozmiar ramki w arcsec), więc progi nie zależą od zoomu
ani od odległości od kamery.

Wygląd to histogram HSV tułowia (między barkami a biodrami z punktów COCO). Kolor
ubrania rozstrzyga skrzyżowania i powrót po utracie; bez nowego modelu.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

import cv2
import numpy as np

from .detectors import Detection
from .perception import KEYPOINT_MIN_CONF, head_point

ToWorld = Callable[[float, float], tuple[float, float]]

# Bramka położenia (w wysokościach ciała): stała część + przyrost z czasem nieobecności.
GATE_BASE = 0.6
GATE_SPEED = 1.0                 # ~chód: 0,8 wysokości ciała na sekundę
GATE_MAX = 3.0
SIZE_MAX = 0.7                   # |ln(rozmiar wykrycia / rozmiar ścieżki)|
APP_NEUTRAL = 0.35               # koszt wyglądu, gdy brak histogramu
APP_MAX_NEAR = 0.6               # próg Bhattacharyyi tuż po utracie...
APP_MAX_FAR = 0.4                # ...i po APP_FAR_S sekundach nieobecności
APP_FAR_S = 3.0
APP_WEIGHT = 1.0
SIZE_WEIGHT = 0.5
AMBIGUITY = 0.1                  # przejęcie zawieszonej ścieżki wymaga tej przewagi w WYGLĄDZIE (nie w odległości)
PREDICT_MAX_S = 0.5              # dłużej nie ekstrapolujemy prędkości
ALPHA, BETA = 0.6, 0.3           # filtr alfa-beta położenia
RETAIN_S = 1.5                   # tyle żyje ścieżka bez wykrycia (poza chronioną)
HIST_MIX = 0.15                  # udział nowej klatki w uśrednianym histogramie
HIST_BINS = (6, 3, 3)            # H, S, V
MIN_ROI = 6                      # px; mniejszy wycinek = brak histogramu


@dataclass
class Track:
    id: int
    pan: float                   # punkt głowy w świecie [arcsec]
    tilt: float
    size: float                  # wysokość ramki w świecie [arcsec]
    last_seen: float
    v_pan: float = 0.0
    v_tilt: float = 0.0
    hist: np.ndarray | None = None
    det: Detection | None = None     # wykrycie dopasowane w TEJ klatce; None = ścieżka zawieszona
    head_px: tuple[float, float] = (0.0, 0.0)     # ostatnia znana głowa i ramka (px klatki)
    box: tuple[int, int, int, int] = (0, 0, 0, 0)
    misses: int = 0


@dataclass(frozen=True)
class TrackInfo:
    """Niezmienna migawka ścieżki dla interfejsu (TrackerState)."""
    id: int
    box: tuple[int, int, int, int]      # ostatnia znana ramka (przy zawieszonej - z ostatniej klatki)
    head: tuple[float, float]
    visible: bool


def torso_hist(frame_bgr: np.ndarray, det: Detection) -> np.ndarray | None:
    """Znormalizowany histogram HSV tułowia albo None, gdy nie da się go wyciąć."""
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
    else:                            # bez barków: pas pod głową, środek ramki
        x0, x1 = det.x + 0.2 * det.w, det.x + 0.8 * det.w
        y0, y1 = det.y + 0.15 * det.h, det.y + 0.55 * det.h
    # ściągamy obszar do środka - brzegi łapią tło
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
        """Przypisuje wykrycia do ścieżek; zwraca wszystkie żywe (widoczne i zawieszone).

        ``protect``/``protect_s``: ścieżka wybrana przez użytkownika żyje bez wykrycia
        do ``protect_s`` sekund (reszta - ``RETAIN_S``)."""
        meas = []
        for d in dets:
            hx, hy = head_point(d)
            pan, tilt = to_world(hx, hy)
            cx = d.x + d.w / 2.0
            size = abs(to_world(cx, d.y)[1] - to_world(cx, d.y + d.h)[1])
            meas.append((d, pan, tilt, max(size, 1.0), torso_hist(frame_bgr, d), (hx, hy)))
        tracks = list(self.tracks.values())
        cost: dict[tuple[int, int], float] = {}
        looks: dict[tuple[int, int], float] = {}     # sam koszt wyglądu tych par
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
        """Zawieszoną ścieżkę przejmujemy tylko przy wyraźnej przewadze rywala w wyglądzie.
        Po kilku sekundach położenie waży mało (bramka rośnie), więc odległość nie może
        rozstrzygać między dwiema osobami w podobnym ubraniu."""
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
    """ID widocznej osoby pod punktem klatki; przy nakładających się ramkach - o bliższej głowie."""
    best, best_d = None, math.inf
    for info in infos:
        bx, by, bw, bh = info.box
        if info.visible and bx <= x <= bx + bw and by <= y <= by + bh:
            d = math.hypot(x - info.head[0], y - info.head[1])
            if d < best_d:
                best, best_d = info.id, d
    return best


AUTO, SELECTED, SUSPENDED = "auto", "wybrana", "zawieszona"
GAP_S = 0.5                      # tyle bez wykrycia wybrana jeszcze "widoczna" (ekstrapolacja)


class TargetSelection:
    """Wybór użytkownika: AUTO -> WYBRANA <-> ZAWIESZONA -> AUTO po ``hold_s``."""

    def __init__(self, hold_s: float = 6.0) -> None:
        self.hold_s = hold_s
        self.state = AUTO
        self.track_id: int | None = None
        self.event = ""
        self._seen = 0.0

    def select(self, track_id: int, t: float) -> None:
        self.state, self.track_id, self.event, self._seen = SELECTED, track_id, "", t

    def clear(self) -> None:
        self.state, self.track_id, self.event = AUTO, None, ""

    def remaining(self, t: float) -> float:
        if self.state != SUSPENDED:
            return 0.0
        return max(0.0, self.hold_s - (t - self._seen))

    def resolve(self, tracks: list[Track], t: float) -> Track | None:
        """Ścieżka wybranej osoby, gdy jest widoczna; inaczej None. Zmienia stan."""
        if self.state == AUTO:
            return None
        tr = next((x for x in tracks if x.id == self.track_id), None)
        if tr is not None and tr.det is not None:
            self.state, self._seen = SELECTED, t
            return tr
        gap = t - self._seen
        if gap > self.hold_s:
            self.state, self.track_id = AUTO, None
            self.event = "wybrana osoba zniknęła - śledzę najbliższą"
        elif gap > GAP_S:
            self.state = SUSPENDED
        return None
