#!/usr/bin/env python3
"""The preview image box must match what the tracking overlay assumes.

``overlay_shapes`` treats the frame as fitted into the overlay area (contain), top-aligned and centred
horizontally. Flutter draws an ``Image`` smaller than its area at its natural size and never scales it
up, and centres the content when the box is taller than the picture. A 640x360 or 960x540 preview
therefore showed a small picture, or one centred vertically, with the overlay drifting off it. The image
box is sized to the fitted frame (and placed at the top centre by ``align``), so both agree at any resolution.

    .venv/bin/python tests/test_preview_fit.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from runner import run  # noqa: E402

from app import CameraApp  # noqa: E402
from eagleeye.overlay import _fit  # noqa: E402


class CountingImage:
    """Image double that counts every write of its size: each one is a property change sent to the window."""

    def __init__(self) -> None:
        self.writes = 0
        self._width = self._height = None

    @property
    def width(self):
        return self._width

    @width.setter
    def width(self, value) -> None:
        self.writes += 1
        self._width = value

    @property
    def height(self):
        return self._height

    @height.setter
    def height(self, value) -> None:
        self.writes += 1
        self._height = value


def make_app(frame_w: int = 640, frame_h: int = 360, stream: bool = True):
    app = CameraApp.__new__(CameraApp)
    app.preview = CountingImage()
    app._overlay_size = (0.0, 0.0)
    app._fitted = None
    app.engine = SimpleNamespace(
        stream=SimpleNamespace(actual_width=frame_w, actual_height=frame_h) if stream else None)
    return app


def test_small_frame_is_scaled_up_to_the_fitted_size_the_overlay_uses() -> None:
    app = make_app(640, 360)
    app._on_overlay_resize(SimpleNamespace(width=1243.0, height=1070.0))
    scale, _, _ = _fit(1243.0, 1070.0, 640, 360)
    assert (app.preview.width, app.preview.height) == (round(640 * scale), round(360 * scale))
    assert app.preview.height < 1070.0                   # not stretched over the whole area: no vertical centring


def test_large_frame_is_scaled_down_to_the_same_fit() -> None:
    app = make_app(1920, 1080)
    app._on_overlay_resize(SimpleNamespace(width=1243.0, height=1070.0))
    scale, _, _ = _fit(1243.0, 1070.0, 1920, 1080)
    assert (app.preview.width, app.preview.height) == (round(1920 * scale), round(1080 * scale))


def test_a_tall_frame_is_limited_by_the_height() -> None:
    app = make_app(640, 360)
    app._on_overlay_resize(SimpleNamespace(width=2000.0, height=400.0))
    assert app.preview.height == 400 and abs(app.preview.width - 400.0 * 640 / 360) <= 0.5


def test_an_unchanged_area_and_frame_size_cause_no_further_writes() -> None:
    app = make_app(640, 360)
    app._on_overlay_resize(SimpleNamespace(width=1243.0, height=1070.0))
    writes = app.preview.writes
    for _ in range(100):                                  # the preview loop calls this on every frame
        app._fit_preview()
    app._on_overlay_resize(SimpleNamespace(width=1243.2, height=1069.9))      # jitter below a pixel
    assert app.preview.writes == writes
    app._on_overlay_resize(SimpleNamespace(width=900.0, height=1070.0))       # a real change
    assert app.preview.writes > writes


def test_a_new_frame_size_is_followed() -> None:
    app = make_app(640, 360)
    app._on_overlay_resize(SimpleNamespace(width=1243.0, height=1070.0))
    app.engine.stream.actual_width, app.engine.stream.actual_height = 1920, 1080     # "Resolution" changed
    app._fit_preview()
    scale, _, _ = _fit(1243.0, 1070.0, 1920, 1080)
    assert (app.preview.width, app.preview.height) == (round(1920 * scale), round(1080 * scale))


def test_nothing_is_set_without_an_area_or_a_stream() -> None:
    app = make_app(640, 360)
    app._on_overlay_resize(SimpleNamespace(width=0.0, height=0.0))
    assert (app.preview.width, app.preview.height) == (None, None)
    app = make_app(stream=False)
    app._on_overlay_resize(SimpleNamespace(width=1243.0, height=700.0))
    assert (app.preview.width, app.preview.height) == (None, None)


if __name__ == "__main__":
    run(globals(), "Preview fit")
