#!/usr/bin/env python3
"""Testy detekcji: model pozy RTMO-s (GPU i CPU) i dekoder klatek MJPEG.

Uruchomienie::

    .venv/bin/python tests/test_detectors.py

Obraz referencyjny (messi5 z osobą) pochodzi z repozytorium próbek OpenCV i są dociągane do ``models/testdata/`` przy pierwszym uruchomieniu.
Jeśli nie ma sieci, testy zależne od obrazów zgłaszają to i są pomijane - nie
udają, że coś sprawdziły.
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
    """Zwraca ścieżkę do obrazu testowego, dociągając go w razie potrzeby."""
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
        raise RuntimeError("brak messi5.jpg albo modelu RTMO (models/, patrz README) - test pominięty")
    det = PoseDetector(prefer_gpu=prefer_gpu)
    return det, det.detect(cv2.imread(str(image_path)))


def test_pose_detector_finds_person_with_head_keypoints() -> None:
    """RTMO-s: osoba wykryta, widoczne punkty głowy leżą razem w górnej części ramki.

    Na messi5.jpg głowa jest mała i pochylona - jedno oko ma pewność 0,26 - więc
    sprawdzamy położenie widocznych punktów, a nie widoczność każdego z osobna.
    """
    det, dets = _messi_pose(True)
    print(f"    backend: {det.backend}, osób: {len(dets)}")
    assert dets, "nie wykryto osoby na messi5.jpg"
    best = max(dets, key=lambda d: d.score)
    assert best.label == "poza" and best.keypoints is not None and len(best.keypoints) == 17
    head = [(x, y) for x, y, c in best.keypoints[:5] if c > 0.3]
    print(f"      widoczne punkty głowy: {[(round(x), round(y)) for x, y in head]}")
    assert len(head) >= 2, "za mało widocznych punktów głowy"
    nx, ny, _ = best.keypoints[0]
    assert best.x <= nx <= best.x + best.w and best.y <= ny <= best.y + best.h * 0.4, \
        "nos poza górną częścią ramki osoby"
    assert all(abs(x - nx) < 25 and abs(y - ny) < 25 for x, y in head), "punkty głowy rozrzucone"


def test_pose_gpu_matches_cpu() -> None:
    _, gpu = _messi_pose(True)
    _, cpu = _messi_pose(False)
    assert len(gpu) == len(cpu), f"liczba osób GPU {len(gpu)} != CPU {len(cpu)}"
    g = max(gpu, key=lambda d: d.score)
    c = max(cpu, key=lambda d: d.score)
    err = max(abs(a - b) for pg, pc in zip(g.keypoints, c.keypoints) for a, b in zip(pg[:2], pc[:2]))
    print(f"    największa różnica punktu GPU/CPU: {err:.2f} px")
    assert err < 2.0


def test_decode_mjpeg_matches_opencv() -> None:
    """Nasz dekoder (Pillow) musi dawać identyczny obraz jak cv2.imdecode."""
    sample = next((p for p in sorted((ROOT / "captures").glob("frame-*.jpg"))), None)
    if sample is None:
        raise RuntimeError("brak zrzutu z kamery w captures/ - test pominięty")
    data = sample.read_bytes()
    ours = decode_mjpeg(data)
    reference = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    assert ours is not None and reference is not None
    assert ours.shape == reference.shape, f"{ours.shape} != {reference.shape}"
    assert np.array_equal(ours, reference), "dekodery dają różne obrazy"
    print(f"    {sample.name}: {ours.shape}, obrazy identyczne")


def test_gpu_status_reports_device() -> None:
    status = gpu_status()
    print(f"    {status}")
    if status["available"]:
        assert status["device"], "GPU zgłoszone jako dostępne, ale bez nazwy urządzenia"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(f"Testy detektorów ({len(tests)}):\n")
    failures = skipped = 0
    for test in tests:
        print(f"- {test.__name__}")
        try:
            test()
        except RuntimeError as exc:  # warunek wstępny, nie błąd kodu
            skipped += 1
            print(f"    POMINIĘTY: {exc}")
        except AssertionError as exc:
            failures += 1
            print(f"    NIEUDANY: {exc}")
    print()
    if failures:
        print(f"WYNIK: {failures} nieudanych, {skipped} pominiętych z {len(tests)}")
        sys.exit(1)
    print(f"WYNIK: {len(tests) - skipped} przeszło, {skipped} pominiętych z {len(tests)}")
