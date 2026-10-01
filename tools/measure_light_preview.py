#!/usr/bin/env python3
"""Cost of showing the light correction in the preview: JPEG decode, table, JPEG encode.

The preview hands raw JPEG bytes to Flet, so while a correction is active every preview frame
goes through ``lightfix.correct_jpeg``. Design gate: 8 ms per frame (a quarter of the 33 ms budget
at 30 fps) at the configured preview size. Above the gate the preview stays raw and only the badge
says the correction is active. The test frame is blurred noise, so it is a pessimistic JPEG.

    .venv/bin/python tools/measure_light_preview.py [width height]
"""

from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eagleeye.lightfix import build_lut, correct_jpeg  # noqa: E402

GATE_MS = 8.0


def main(argv: list[str]) -> int:
    width, height = (int(argv[1]), int(argv[2])) if len(argv) >= 3 else (1280, 720)
    noise = np.random.default_rng(1).integers(0, 255, (height, width, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", cv2.GaussianBlur(noise, (0, 0), 3), [cv2.IMWRITE_JPEG_QUALITY, 90])
    jpg = buf.tobytes()
    lut = build_lut(40.0)
    for _ in range(5):
        correct_jpeg(jpg, lut)
    times = []
    for _ in range(60):
        started = time.perf_counter()
        out = correct_jpeg(jpg, lut)
        times.append((time.perf_counter() - started) * 1000.0)
        assert out is not None
    median = statistics.median(times)
    print(f"{width}x{height}: median {median:.1f} ms, worst {max(times):.1f} ms, JPEG {len(jpg) // 1024} KiB")
    print(f"gate {GATE_MS:.0f} ms -> PREVIEW_CORRECTION = {median <= GATE_MS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
