#!/usr/bin/env python3
"""The tracking illustration (tools/render_sim_screenshot.py) renders, and what its captions
claim is true for the simulation behind it.

    .venv/bin/python tests/test_render_sim_screenshot.py
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402
from runner import run  # noqa: E402

_spec = importlib.util.spec_from_file_location("render_sim_screenshot", ROOT / "tools" / "render_sim_screenshot.py")
tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tool)


def render_once(at: float = 26.0) -> tuple[Path, dict]:
    out = Path(tempfile.mkdtemp()) / "tracking.png"
    return out, tool.render(at, out)


def test_renders_an_image_of_the_expected_size() -> None:
    out, _ = render_once()
    with Image.open(out) as im:
        assert im.size == (1840, 700)


def test_preview_frame_shows_the_head_on_the_aim_point() -> None:
    _, info = render_once()
    x, y = info["head_px"]
    assert abs(x - 0.5 * tool.FRAME[0]) < 15 and abs(y - tool.GOLDEN * tool.FRAME[1]) < 15, info


def test_the_camera_answers_once_after_a_short_delay_and_comes_back() -> None:
    _, info = render_once()
    assert 0.5 < info["reaction_s"] < 3.0, "the caption says the camera answers after a short dwell"
    assert abs(info["camera_end_deg"]) < 1.0, "after the person returns the camera is back near the start"


if __name__ == "__main__":
    run(globals(), "Tracking illustration")
