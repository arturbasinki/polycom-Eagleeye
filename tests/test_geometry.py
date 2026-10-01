#!/usr/bin/env python3
"""Geometria kamery: pole widzenia, zoom, przeliczenia piksel <-> kąt świata.

    .venv/bin/python tests/test_geometry.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from runner import run  # noqa: E402

from eagleeye.geometry import (HFOV_WIDE_ARCSEC, ZOOM_MAX_FACTOR, ZOOM_MAX_VALUE,  # noqa: E402
                               View, deg, zoom_factor, zoom_value_for)


def close(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def test_deg_converts_to_arcsec() -> None:
    assert deg(1.5) == 5400.0


def test_center_pixel_is_camera_direction() -> None:
    assert View(1280, 720).pixel_to_world(640, 360, 1000.0, -500.0) == (1000.0, -500.0)


def test_right_edge_is_half_fov_to_the_right() -> None:
    pan, tilt = View(1280, 720).pixel_to_world(1280, 360, 0.0, 0.0)
    assert close(pan, HFOV_WIDE_ARCSEC / 2) and tilt == 0.0


def test_top_of_frame_is_up() -> None:
    _, tilt = View(1280, 720).pixel_to_world(640, 0, 0.0, 0.0)
    assert tilt > 0


def test_round_trip() -> None:
    v = View(960, 540, zoom_value=2000)
    world = v.pixel_to_world(100.0, 400.0, 3600.0, 7200.0)
    x, y = v.world_to_pixel(*world, 3600.0, 7200.0)
    assert close(x, 100.0) and close(y, 400.0)


def test_full_zoom_narrows_fov() -> None:
    assert close(View(1280, 720, zoom_value=ZOOM_MAX_VALUE).hfov, HFOV_WIDE_ARCSEC / ZOOM_MAX_FACTOR)


def test_zoom_follows_measured_curve() -> None:
    # Pomiar 2026-09-24 (dopasowanie klatki z zoomem do klatki bez zoomu, 1920x1080):
    # zoom 800 -> 1.23x, 2400 -> 1.99x, 4000 -> 3.80x. Model liniowy dawał 5.65x przy 2400,
    # przez co każdy ruch pokonywał ~35% drogi (śledzenie „na raty”).
    for value, measured in ((800, 1.233), (2400, 1.985), (4000, 3.804)):
        assert abs(zoom_factor(value) / measured - 1.0) < 0.02, (value, zoom_factor(value))
    fov_2400 = View(1280, 720, zoom_value=2400).hfov / 3600
    assert 35.0 < fov_2400 < 38.0              # zmierzone 36.1° (dopasowanie) i 37.2° (ruch pan)


def test_zoom_factor_is_monotonic_from_1_to_max() -> None:
    values = [zoom_factor(z) for z in range(0, ZOOM_MAX_VALUE + 1, 40)]
    assert values[0] == 1.0 and close(values[-1], ZOOM_MAX_FACTOR)
    assert all(b > a for a, b in zip(values, values[1:]))


def test_vfov_follows_aspect_ratio() -> None:
    v = View(1280, 720)
    assert close(v.vfov, v.hfov * 720 / 1280)


def test_invert_pan_flips_direction() -> None:
    pan, _ = View(1280, 720, invert_pan=True).pixel_to_world(1280, 360, 0.0, 0.0)
    assert pan < 0


def test_same_angle_at_any_resolution() -> None:
    full = View(1280, 720).pixel_to_world(1000, 200, 0.0, 0.0)
    half = View(640, 360).pixel_to_world(500, 100, 0.0, 0.0)
    assert close(full[0], half[0]) and close(full[1], half[1])


def test_zoom_value_for_inverts_zoom_factor() -> None:
    for z in range(0, ZOOM_MAX_VALUE + 1, 40):
        assert abs(zoom_value_for(zoom_factor(z)) - z) < 1.0, z


def test_zoom_value_for_clamps_outside_range() -> None:
    assert zoom_value_for(0.5) == 0.0
    assert zoom_value_for(50.0) == ZOOM_MAX_VALUE


if __name__ == "__main__":
    run(globals(), "Geometria")
