#!/usr/bin/env python3
"""Detection tests: the RTMO-s pose model (GPU and CPU) and the MJPEG frame decoder.

Running::

    .venv/bin/python tests/test_detectors.py

The reference image (messi5 with a person) comes from the OpenCV sample repository and is
downloaded to ``models/testdata/`` on first run. Without a network, the image-dependent
tests report that and are skipped - they do not pretend to have checked anything.
"""

from __future__ import annotations

import sys
import urllib.error
import urllib.request
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eagleeye.detectors import RTMO_MODEL, PoseDetector, decode_mjpeg, gpu_status  # noqa: E402

TESTDATA = ROOT / "models" / "testdata"
SAMPLES = "https://raw.githubusercontent.com/opencv/opencv/4.x/samples/data"


def ensure(name: str) -> Path | None:
    """Return the path to the test image, downloading it if needed."""
    path = TESTDATA / name
    if path.exists():
        return path
    TESTDATA.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(f"{SAMPLES}/{name}", timeout=20) as response:
            path.write_bytes(response.read())
        return path
    except (urllib.error.URLError, TimeoutError, OSError):
        return None


def _messi_pose(prefer_gpu: bool):
    image_path = ensure("messi5.jpg")
    if image_path is None or not RTMO_MODEL.exists():
        raise RuntimeError("no messi5.jpg or RTMO model (models/, see README) - test skipped")
    det = PoseDetector(prefer_gpu=prefer_gpu)
    return det, det.detect(cv2.imread(str(image_path)))


def test_pose_detector_finds_person_with_head_keypoints() -> None:
    """RTMO-s: person detected, the visible head points lie together in the upper part of the box.

    On messi5.jpg the head is small and tilted - one eye has a confidence of 0.26 - so we
    check the position of the visible points, not the visibility of each of them.
    """
    det, dets = _messi_pose(True)
    print(f"    backend: {det.backend}, people: {len(dets)}")
    assert dets, "no person detected in messi5.jpg"
    best = max(dets, key=lambda d: d.score)
    assert best.label == "poza" and best.keypoints is not None and len(best.keypoints) == 17
    head = [(x, y) for x, y, c in best.keypoints[:5] if c > 0.3]
    print(f"      visible head points: {[(round(x), round(y)) for x, y in head]}")
    assert len(head) >= 2, "too few visible head points"
    nx, ny, _ = best.keypoints[0]
    assert best.x <= nx <= best.x + best.w and best.y <= ny <= best.y + best.h * 0.4, \
        "nose outside the upper part of the person box"
    assert all(abs(x - nx) < 25 and abs(y - ny) < 25 for x, y in head), "head points scattered"


def test_pose_gpu_matches_cpu() -> None:
    _, gpu = _messi_pose(True)
    _, cpu = _messi_pose(False)
    assert len(gpu) == len(cpu), f"GPU people {len(gpu)} != CPU {len(cpu)}"
    g = max(gpu, key=lambda d: d.score)
    c = max(cpu, key=lambda d: d.score)
    err = max(abs(a - b) for pg, pc in zip(g.keypoints, c.keypoints) for a, b in zip(pg[:2], pc[:2]))
    print(f"    largest GPU/CPU point difference: {err:.2f} px")
    assert err < 2.0


def test_decode_mjpeg_matches_opencv() -> None:
    """Our decoder (Pillow) must give an image identical to cv2.imdecode."""
    sample = next((p for p in sorted((ROOT / "captures").glob("frame-*.jpg"))), None)
    if sample is None:
        raise RuntimeError("no camera capture in captures/ - test skipped")
    data = sample.read_bytes()
    ours = decode_mjpeg(data)
    reference = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    assert ours is not None and reference is not None
    assert ours.shape == reference.shape, f"{ours.shape} != {reference.shape}"
    assert np.array_equal(ours, reference), "the decoders give different images"
    print(f"    {sample.name}: {ours.shape}, images identical")


def test_gpu_status_reports_device() -> None:
    status = gpu_status()
    print(f"    {status}")
    if status["available"]:
        assert status["device"], "GPU advertised as available but with no device name"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(f"Detector tests ({len(tests)}):\n")
    failures = skipped = 0
    for test in tests:
        print(f"- {test.__name__}")
        try:
            test()
        except RuntimeError as exc:  # a precondition, not a code error
            skipped += 1
            print(f"    SKIPPED: {exc}")
        except AssertionError as exc:
            failures += 1
            print(f"    FAILED: {exc}")
    print()
    if failures:
        print(f"RESULT: {failures} failed, {skipped} skipped of {len(tests)}")
        sys.exit(1)
    print(f"RESULT: {len(tests) - skipped} passed, {skipped} skipped of {len(tests)}")
