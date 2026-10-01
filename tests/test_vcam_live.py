#!/usr/bin/env python3
"""Wirtualna kamera na prawdziwym urządzeniu: zapis i odczyt z drugiej strony (OpenCV).

Wymaga modułu v4l2loopback z kartą "EagleEye" i wolnej kamery.

    .venv/bin/python tests/test_vcam_live.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from runner import run  # noqa: E402

from eagleeye.detectors import decode_mjpeg  # noqa: E402
from eagleeye.v4l2 import MjpegStream, V4L2Error, find_device_by_card  # noqa: E402
from eagleeye.vcam import CARD_LABEL, VirtualCamera  # noqa: E402


def read_output(path: str):
    cap = cv2.VideoCapture(path, cv2.CAP_V4L2)
    try:
        for _ in range(10):
            ok, frame = cap.read()
            if ok:
                return frame
            time.sleep(0.1)
        return None
    finally:
        cap.release()


def test_output_matches_camera_and_privacy_card() -> None:
    path = find_device_by_card(CARD_LABEL)
    if path is None:
        print("    POMINIĘTY: brak urządzenia EagleEye (Task 2, krok 6)")
        return
    try:
        stream = MjpegStream("/dev/video0", 1280, 720)
        stream.start()
    except (OSError, V4L2Error) as exc:
        print(f"    POMINIĘTY: kamera zajęta ({exc})")
        return
    vc = VirtualCamera()
    vc.set_source(stream)
    vc.start()
    try:
        time.sleep(1.5)
        out = read_output(path)
        _, jpg, _ = stream.frame_timed(0)
        cam = decode_mjpeg(jpg)
        assert out is not None and out.shape == (720, 1280, 3), f"odczyt z {path} nie działa"
        g1 = cv2.resize(cv2.cvtColor(out, cv2.COLOR_BGR2GRAY), (160, 90)).astype(float).ravel()
        g2 = cv2.resize(cv2.cvtColor(cam, cv2.COLOR_BGR2GRAY), (160, 90)).astype(float).ravel()
        corr = float(np.corrcoef(g1, g2)[0, 1])
        print(f"    {path}: {out.shape}, korelacja z kamerą {corr:.2f}, status {vc.status}")
        assert corr > 0.8
        vc.set_privacy(True)
        time.sleep(0.5)
        card = read_output(path)
        print(f"    plansza: średnia jasność {card.mean():.0f}")
        assert card.mean() < 60, "plansza prywatności powinna być ciemna"
    finally:
        vc.stop()
        stream.stop()


if __name__ == "__main__":
    run(globals(), "Wirtualna kamera na sprzęcie")
