"""Planer punktów skanu: gdzie kamera ma popatrzeć, szukając osoby.

Pole widzenia to ~72°, więc punkty co 60° zachodzą na siebie. Najpierw punkt
startowy (ostatni znany azymut - osoba najpewniej jest blisko), potem
przemiatanie w stronę, gdzie zostało więcej zakresu, aż do granicy, i na końcu
druga strona. Naprzemienne +60/-60/+120/... wymagałoby coraz dłuższych
przejazdów przez środek: pełny rząd trwałby ~48 s zamiast ~24 s.
"""

from __future__ import annotations

from .geometry import deg

SCAN_STEP = deg(60)
SECOND_ROW_OFFSET = deg(20)   # głowa stojącej osoby blisko kamery: +25..+32° (zmierzone)
_SAME = deg(1)      # punkty bliżej niż 1° traktujemy jako ten sam


def _clamp(value: float, limits: tuple[float, float]) -> float:
    return min(max(value, limits[0]), limits[1])


def pan_sequence(start: float, pan_min: float, pan_max: float, step: float = SCAN_STEP) -> list[float]:
    start = _clamp(start, (pan_min, pan_max))
    first = 1 if (pan_max - start) >= (start - pan_min) else -1

    def side(direction: int) -> list[float]:
        points: list[float] = []
        k = 1
        while pan_min <= start + direction * k * step <= pan_max:
            points.append(start + direction * k * step)
            k += 1
        edge = pan_max if direction > 0 else pan_min
        if abs(edge - (points[-1] if points else start)) > step / 2:
            points.append(edge)
        return points

    return [start] + side(first) + side(-first)


def startup_plan(start_pan: float, work_tilt: float, pan_limits: tuple[float, float],
                 tilt_limits: tuple[float, float]) -> list[tuple[float, float]]:
    """Pełny skan: rząd na wysokości roboczej, potem z powrotem rzędem o 10° wyżej."""
    tilt1 = _clamp(work_tilt, tilt_limits)
    tilt2 = _clamp(work_tilt + SECOND_ROW_OFFSET, tilt_limits)
    pans = pan_sequence(start_pan, *pan_limits)
    return [(p, tilt1) for p in pans] + [(p, tilt2) for p in reversed(pans)]


def local_plan(center_pan: float, tilt: float, hfov: float,
               pan_limits: tuple[float, float]) -> list[tuple[float, float]]:
    """Szukanie lokalne: środek i po jednym polu widzenia w obie strony."""
    out: list[float] = []
    for p in (center_pan, center_pan + hfov, center_pan - hfov):
        p = _clamp(p, pan_limits)
        if all(abs(p - q) > _SAME for q in out):
            out.append(p)
    return [(p, tilt) for p in out]
