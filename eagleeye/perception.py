"""Percepcja: z klatki punkt głowy celu (Observation) i lista wykryć do podglądu.

Źródłem jest jeden model pozy (RTMO-s): dla każdej osoby 17 punktów COCO.
Punkt głowy to średnia widocznych punktów nosa, oczu i uszu - istnieje
przodem, w profilu, stojąc i tyłem. Wcześniej twarz (YuNet) i sylwetka
(YOLOX) były dwoma źródłami, a przełączanie między nimi przesuwało cel
o 9-13° przy wstawaniu, siadaniu i odwracaniu się (spike 2026-09-23;
RTMO-s w tych samych chwilach najwyżej 3-5°).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .detectors import Detection, PoseDetector

HEAD_KEYPOINTS = 5          # COCO: 0 nos, 1-2 oczy, 3-4 uszy
KEYPOINT_MIN_CONF = 0.3     # reguła z pomiarów spike'u
# Skala kary za odległość od poprzedniego celu (ułamek przekątnej klatki).
ASSOCIATION_SCALE = 0.15


@dataclass(frozen=True)
class Observation:
    x: float                          # punkt głowy w pikselach klatki
    y: float
    t: float                          # czas powstania klatki (CLOCK_MONOTONIC)
    score: float
    source: str                       # "poza"
    box: tuple[int, int, int, int]
    yaw: float | None = None          # kierunek twarzy: + nos na prawo w obrazie (framing)
    head_scale_px: float | None = None  # odcinek oczy→barki w pikselach klatki


def head_point(det: Detection) -> tuple[float, float]:
    """Średnia widocznych punktów głowy; gdy żadnego nie widać - środek górnej krawędzi
    ramki (głowa nad kadrem u stojącej osoby blisko kamery: kamera ma jechać w górę)."""
    if det.keypoints:
        pts = [(x, y) for x, y, c in det.keypoints[:HEAD_KEYPOINTS] if c > KEYPOINT_MIN_CONF]
        if pts:
            return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
    return det.x + det.w / 2.0, float(det.y)


def _visible(det: Detection, indices: tuple[int, ...]) -> list[tuple[float, float]]:
    kps = det.keypoints or ()
    return [(kps[i][0], kps[i][1]) for i in indices if i < len(kps) and kps[i][2] > KEYPOINT_MIN_CONF]


def face_yaw(det: Detection) -> float | None:
    """Wskaźnik odwrócenia głowy w [-1, 1]: położenie nosa względem środka widocznych oczu
    i uszu, w połowach ich rozpiętości. Dodatni = nos na prawo w obrazie (twarz zwrócona
    w prawo kadru). Proporcja w obrębie twarzy - nie zależy od odległości ani zoomu."""
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
    """Skala głowy: pionowy odcinek linia oczu → linia barków (px). Bez widocznych barków
    - None (nie szacujemy z odległości oczu: iloraz oczy→barki zależy od obrotu głowy,
    2026-09-25, więc przełączanie źródeł pompowałoby zoom); filtr utrzymuje ostatnią
    miarę."""
    eyes = _visible(det, (1, 2))
    shoulders = _visible(det, (5, 6))
    if eyes and shoulders:
        eye_y = sum(p[1] for p in eyes) / len(eyes)
        shoulder_y = sum(p[1] for p in shoulders) / len(shoulders)
        return abs(shoulder_y - eye_y)
    return None


def pick(cands: list[Detection], previous: tuple[float, float] | None,
         frame_w: int, frame_h: int) -> Detection | None:
    """Bez poprzedniego celu: największa osoba (najbliższa). Z nim: rozmiar
    z wykładniczą karą za odległość - cel nie przeskakuje na innego człowieka."""
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
        """Obserwacja z wybranego wykrycia (głowa, skręt twarzy, skala) - wspólna dla ``pick``
        i dla osoby wskazanej kliknięciem (eagleeye.identity)."""
        x, y = head_point(det)
        return Observation(x, y, t, det.score, det.label, det.as_box(),
                           yaw=face_yaw(det), head_scale_px=head_scale_px(det))


def default_perception(use_gpu: bool) -> Perception:
    return Perception(PoseDetector(prefer_gpu=use_gpu))
