#!/usr/bin/env python3
"""Pomiar dynamiki zoomu -> pola zoom_* w ``Dynamics`` (config.json).

Ruch optyki wykrywamy różnicą kolejnych klatek (czasy z bufora V4L2): powyżej progu
szumu obraz się zmienia, czyli zoom jedzie. Z kilku skoków liczymy:

* zoom_latency - od zapisu kontrolki do pierwszej zmienionej klatki (mediana),
* zoom_base, zoom_speed - prosta: czas jazdy = base + |skok| / speed,
* czy zoom i pan mogą jechać razem: czas do bezruchu dla pan, dla zoomu i dla obu
  naraz, oraz czy po ruchu wspólnym obraz wrócił dokładnie do klatki odniesienia.

Kamera musi być wolna (zamknij aplikację), a kadr powinien mieć teksturę. Pozycja
i zoom są przywracane na końcu - także po Ctrl+C i SIGTERM.

    .venv/bin/python tools/measure_zoom.py           # tylko wypisz
    .venv/bin/python tools/measure_zoom.py --save    # zapisz do config.json

Kalibracja tej kamery jest w kodzie (wartości domyślne ``head_model.Dynamics``) i nie
znika razem z ``config.json``. ``--save`` zapisuje wynik jako nadpisanie w ``config.json``
(np. dla innego egzemplarza); nową kalibrację tego egzemplarza wpisz do ``Dynamics``.
"""

from __future__ import annotations

import argparse
import signal
import statistics
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eagleeye.config import Store  # noqa: E402
from eagleeye.detectors import decode_mjpeg  # noqa: E402
from eagleeye.geometry import deg  # noqa: E402
from eagleeye.v4l2 import CID_PAN_ABSOLUTE, CID_ZOOM_ABSOLUTE, ControlDevice, MjpegStream  # noqa: E402

W, H = 640, 360
JUMPS = ((0, 2400), (2400, 4000), (4000, 2400), (2400, 0), (800, 1600), (1600, 800))
SETTLE = 1.5            # s bez zmian obrazu = koniec ruchu
TIMEOUT = 8.0
PAN_STEP = deg(10)
TOGETHER_SLACK = 0.3    # ruch wspólny może trwać najwyżej tyle dłużej niż dłuższy z pojedynczych
SAME_FRAME_PX = 3.0     # przesunięcie względem odniesienia, poniżej którego to "ta sama klatka"


class Watcher:
    def __init__(self, stream: MjpegStream) -> None:
        self.stream = stream
        self.last = 0

    def gray(self) -> tuple[float, np.ndarray]:
        while True:
            self.last, jpg, ts = self.stream.frame_timed(self.last, timeout=2.0)
            img = decode_mjpeg(jpg) if jpg else None
            if img is not None:
                small = cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (W // 2, H // 2))
                return ts, cv2.GaussianBlur(small, (5, 5), 0).astype(np.float32)

    def threshold(self, seconds: float = 1.5) -> float:
        """Próg ruchu: 4x mediana różnicy kolejnych klatek w bezruchu."""
        _, prev = self.gray()
        diffs = []
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            _, g = self.gray()
            diffs.append(float(np.mean(np.abs(g - prev))))
            prev = g
        return 4.0 * max(statistics.median(diffs), 0.2)

    def motion(self, action, thr: float) -> tuple[float | None, float | None]:
        """Wykonuje ``action``; zwraca (start ruchu, koniec ruchu) w s od chwili zapisu."""
        _, prev = self.gray()
        t0 = time.monotonic()
        action()
        first = last = None
        while True:
            ts, g = self.gray()
            if float(np.mean(np.abs(g - prev))) > thr:
                first = ts - t0 if first is None else first
                last = ts - t0
            prev = g
            elapsed = time.monotonic() - t0
            if last is not None and elapsed - last > SETTLE:
                return first, last
            if elapsed > TIMEOUT:
                return first, last


def settle(ctl: ControlDevice, cid: int, value: int) -> None:
    if ctl.get(cid) != value:
        ctl.set(cid, value)
        time.sleep(3.0)


def fit(rows: list[tuple[int, float, float]]) -> dict:
    """rows: (skok, start, koniec) -> zoom_latency, zoom_base, zoom_speed."""
    latency = statistics.median(r[1] for r in rows)
    xs = np.array([abs(r[0]) for r in rows], float)
    ys = np.array([r[2] - latency for r in rows], float)
    slope, base = np.polyfit(xs, ys, 1)
    return {"zoom_latency": round(latency, 3), "zoom_base": round(max(0.0, float(base)), 3),
            "zoom_speed": round(1.0 / max(float(slope), 1e-5), 1)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--device", default="/dev/video0")
    parser.add_argument("--save", action="store_true", help="zapisz wynik do config.json")
    args = parser.parse_args()

    def interrupted(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)

    ctl = ControlDevice(args.device)
    stream = MjpegStream(args.device, W, H)
    stream.start()
    pan0, zoom0 = ctl.get(CID_PAN_ABSOLUTE), ctl.get(CID_ZOOM_ABSOLUTE)
    try:
        w = Watcher(stream)
        settle(ctl, CID_ZOOM_ABSOLUTE, 0)
        thr = w.threshold()
        print(f"próg ruchu: {thr:.2f}")

        rows = []
        for a, b in JUMPS:
            settle(ctl, CID_ZOOM_ABSOLUTE, a)
            first, last = w.motion(lambda b=b: ctl.set(CID_ZOOM_ABSOLUTE, b), thr)
            print(f"zoom {a:5d} -> {b:5d}: start {first}, koniec {last}")
            if first is not None and last is not None:
                rows.append((b - a, first, last))
        result = fit(rows) if len(rows) >= 3 else {}
        print("wynik:", result or "za mało udanych pomiarów")

        settle(ctl, CID_ZOOM_ABSOLUTE, 0)
        _, reference = w.gray()
        _, t_pan = w.motion(lambda: ctl.set(CID_PAN_ABSOLUTE, pan0 + PAN_STEP), thr)
        _, t_zoom = w.motion(lambda: ctl.set(CID_ZOOM_ABSOLUTE, 2400), thr)

        def both() -> None:
            ctl.set(CID_PAN_ABSOLUTE, pan0)
            ctl.set(CID_ZOOM_ABSOLUTE, 0)
        _, t_both = w.motion(both, thr)
        time.sleep(1.0)
        _, after = w.gray()
        (dx, dy), _ = cv2.phaseCorrelate(reference, after)
        same = float(np.hypot(dx, dy)) < SAME_FRAME_PX
        fast = None not in (t_pan, t_zoom, t_both) and t_both <= max(t_pan, t_zoom) + TOGETHER_SLACK
        print(f"pan {t_pan} s, zoom {t_zoom} s, razem {t_both} s, "
              f"przesunięcie po ruchu wspólnym {np.hypot(dx, dy):.1f} px")
        print("ZOOM_WITH_PAN_TILT = True  (zoom i pan/tilt mogą jechać jednocześnie)" if fast and same
              else "ZOOM_WITH_PAN_TILT = False (zoom i pan/tilt kolejno)")

        if args.save and result:
            store = Store()
            store.settings["dynamics"].update(result)
            store.save()
            print("zapisano do config.json")
    except KeyboardInterrupt:
        print("przerwano - przywracam pozycję i zoom")
    finally:
        ctl.set(CID_PAN_ABSOLUTE, pan0 + 1)     # firmware ignoruje wpis równy ostatniemu
        ctl.set(CID_PAN_ABSOLUTE, pan0)
        ctl.set(CID_ZOOM_ABSOLUTE, zoom0)
        stream.stop()
        ctl.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
