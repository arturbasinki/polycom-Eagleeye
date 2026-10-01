"""Scan point planner: where the camera should look while searching for a person.

The field of view is ~72°, so points every 60° overlap. First the start
point (the last known azimuth - the person is most likely close), then
a sweep towards the side with more range left, up to the limit, and finally
the other side. Alternating +60/-60/+120/... would require ever longer
travels through the centre: a full row would take ~48 s instead of ~24 s.
"""

from __future__ import annotations

from .geometry import deg

SCAN_STEP = deg(60)
SECOND_ROW_OFFSET = deg(20)   # head of a person standing close to the camera: +25..+32° (measured)
_SAME = deg(1)      # points closer than 1° we treat as the same


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
    """Full scan: a row at the working height, then back in a row 10° higher."""
    tilt1 = _clamp(work_tilt, tilt_limits)
    tilt2 = _clamp(work_tilt + SECOND_ROW_OFFSET, tilt_limits)
    pans = pan_sequence(start_pan, *pan_limits)
    return [(p, tilt1) for p in pans] + [(p, tilt2) for p in reversed(pans)]


def local_plan(center_pan: float, tilt: float, hfov: float,
               pan_limits: tuple[float, float]) -> list[tuple[float, float]]:
    """Local search: the centre and one field of view to each side."""
    out: list[float] = []
    for p in (center_pan, center_pan + hfov, center_pan - hfov):
        p = _clamp(p, pan_limits)
        if all(abs(p - q) > _SAME for q in out):
            out.append(p)
    return [(p, tilt) for p in out]
