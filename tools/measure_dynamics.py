#!/usr/bin/env python3
"""Pomiar dynamiki głowicy -> parametry ``Dynamics`` w config.json.

Mierzy korelacją faz przesunięcie obrazu między kolejnymi klatkami (czasy
z bufora V4L2) i z tego wyznacza:

* ruch prędkościowy pan: opóźnienie, prędkość przelotową, rozpędzanie, hamowanie,
* ruch absolutny pan: czas przejazdu dla kilku odległości -> abs_base, abs_speed,
  abs_latency; przy okazji sprawdza skalę kątową (zmierzony kąt vs zadany).

Kamera musi być wolna (zamknij aplikację), a kadr powinien mieć teksturę
(nie biała ściana). Na końcu pozycja, zoom i prędkości są przywracane.

    .venv/bin/python tools/measure_dynamics.py           # tylko wypisz
    .venv/bin/python tools/measure_dynamics.py --save    # zapisz do config.json

Kalibracja tej kamery jest w kodzie (wartości domyślne ``head_model.Dynamics``) i nie
znika razem z ``config.json``. ``--save`` zapisuje wynik jako nadpisanie w ``config.json``
(np. dla innego egzemplarza); nową kalibrację tego egzemplarza wpisz do ``Dynamics``.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eagleeye.config import Store  # noqa: E402
from eagleeye.detectors import decode_mjpeg  # noqa: E402
from eagleeye.geometry import View, deg  # noqa: E402
from eagleeye.head_model import Dynamics  # noqa: E402
from eagleeye.v4l2 import (CID_PAN_ABSOLUTE, CID_PAN_SPEED, CID_TILT_SPEED,  # noqa: E402
                           CID_ZOOM_ABSOLUTE, ControlDevice, MjpegStream)

W, H = 640, 360
MOVING = deg(3.0)          # arcsec/s - powyżej tej prędkości uznajemy, że głowica jedzie
DISTANCES_DEG = (2, 5, 10, 20, 40)


class Probe:
    """Nagrywa skumulowany kąt pan z przesunięć obrazu."""

    def __init__(self, stream: MjpegStream) -> None:
        self.stream = stream
        self.last = 0
        self.window = cv2.createHanningWindow((W, H), cv2.CV_32F)
        self.scale = View(W, H).arcsec_per_px

    def _gray(self) -> tuple[float, np.ndarray]:
        while True:
            self.last, jpg, ts = self.stream.frame_timed(self.last, timeout=2.0)
            img = decode_mjpeg(jpg) if jpg else None
            if img is not None:
                return ts, np.float32(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))

    def record(self, seconds: float, actions: list) -> tuple[list[float], list[tuple[float, float]]]:
        """Nagrywa (czas klatki, kąt pan) i wykonuje akcje [(po_ilu_s, funkcja)]."""
        ts, prev = self._gray()
        t0 = time.monotonic()
        pending = sorted(actions, key=lambda a: a[0])
        fired: list[float] = []
        samples = [(ts, 0.0)]
        total = 0.0
        while time.monotonic() - t0 < seconds:
            while pending and time.monotonic() - t0 >= pending[0][0]:
                _, action = pending.pop(0)
                fired.append(time.monotonic())
                action()
            ts, cur = self._gray()
            (dx, _), response = cv2.phaseCorrelate(prev, cur, self.window)
            prev = cur
            if response > 0.05:
                total += -dx * self.scale      # obraz w lewo = kamera w prawo
            samples.append((ts, total))
        return fired, samples


def rates(samples: list[tuple[float, float]]):
    t = np.array([s[0] for s in samples])
    x = np.array([s[1] for s in samples])
    v = np.diff(x) / np.maximum(np.diff(t), 1e-3)
    v = np.convolve(v, np.ones(3) / 3.0, mode="same")     # tłumimy szum korelacji
    return t[1:], v, t, x


def rehome(ctl: ControlDevice, pan: int) -> None:
    """Powrót na ``pan``. Najpierw inna wartość - tę samą firmware by zignorował."""
    ctl.set(CID_PAN_ABSOLUTE, int(pan) + 3600)
    time.sleep(2.5)
    ctl.set(CID_PAN_ABSOLUTE, int(pan))
    time.sleep(2.5)


def measure_velocity(probe: Probe, ctl: ControlDevice) -> dict:
    fired, samples = probe.record(3.0, [(0.3, lambda: ctl.set(CID_PAN_SPEED, 1)),
                                        (1.8, lambda: ctl.set(CID_PAN_SPEED, 0))])
    t_go, t_stop = fired
    tr, v, t, x = rates(samples)
    moving = tr[np.abs(v) > MOVING]
    if len(moving) < 3:
        raise RuntimeError("nie wykryto ruchu prędkościowego - czy kadr ma teksturę?")
    start = float(moving[0])
    speed = float(np.median(v[(tr > start + 0.5) & (tr < t_stop)]))
    reach = float(tr[(tr > start) & (v >= 0.9 * speed)][0])
    latency = start - t_go
    coast = float(x[-1] - np.interp(t_stop, t, x))
    decel = max(0.05, 2.0 * (coast / speed - latency))
    print(f"prędkość: {speed / 3600:.1f}°/s, opóźnienie {latency:.3f} s, rozpędzanie "
          f"{reach - start:.3f} s, wybieg {coast / 3600:.1f}° -> hamowanie {decel:.3f} s")
    return {"vel_speed": speed, "vel_latency": latency, "vel_ramp": reach - start, "vel_decel": decel}


def measure_absolute(probe: Probe, ctl: ControlDevice, pan0: int) -> dict:
    side = -1 if pan0 > 0 else 1           # jedziemy w stronę, gdzie jest miejsce
    rows = []
    for d in DISTANCES_DEG:
        target = int(pan0 + side * deg(d))
        fired, samples = probe.record(3.5, [(0.3, lambda tg=target: ctl.set(CID_PAN_ABSOLUTE, tg))])
        tr, v, _, x = rates(samples)
        moving = tr[np.abs(v) > MOVING]
        ctl.set(CID_PAN_ABSOLUTE, int(pan0))
        time.sleep(3.0)
        if len(moving) < 2:
            print(f"  {d:>3}°: nie wykryto ruchu - pomijam")
            continue
        duration = float(moving[-1] - moving[0])
        rows.append((deg(d), float(moving[0] - fired[0]), duration))
        print(f"  {d:>3}°: czas {duration:.3f} s, opóźnienie {moving[0] - fired[0]:.3f} s, "
              f"zmierzony kąt {abs(x[-1]) / 3600:.1f}°")
    if len(rows) < 2:
        raise RuntimeError("za mało udanych przejazdów absolutnych")
    slope, base = np.polyfit([r[0] for r in rows], [r[2] for r in rows], 1)
    return {"abs_latency": float(np.median([r[1] for r in rows])),
            "abs_base": float(max(0.05, base)),
            "abs_speed": float(1.0 / max(slope, 1e-9))}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--device", default="/dev/video0")
    parser.add_argument("--save", action="store_true", help="zapisz wynik do config.json")
    args = parser.parse_args()

    ctl = ControlDevice(args.device)
    stream = MjpegStream(args.device, W, H)
    stream.start()
    pan0 = ctl.get(CID_PAN_ABSOLUTE)
    zoom0 = ctl.get(CID_ZOOM_ABSOLUTE)
    try:
        ctl.set(CID_PAN_SPEED, 0)
        ctl.set(CID_TILT_SPEED, 0)
        ctl.set(CID_ZOOM_ABSOLUTE, 0)
        time.sleep(2.0)
        probe = Probe(stream)
        print("ruch prędkościowy (pan):")
        values = measure_velocity(probe, ctl)
        rehome(ctl, pan0)
        print("ruch absolutny (pan):")
        values.update(measure_absolute(probe, ctl, pan0))
    finally:
        ctl.set(CID_PAN_SPEED, 0)
        ctl.set(CID_TILT_SPEED, 0)
        rehome(ctl, pan0)
        ctl.set(CID_ZOOM_ABSOLUTE, zoom0)
        stream.stop()
        ctl.close()

    dyn = Dynamics(**values)
    print("\nDynamics:")
    for key, value in values.items():
        print(f"  {key:12s} = {value:.4f}")
    print(f"  wybieg po stop: {dyn.coast_distance() / 3600:.1f}°")
    if args.save:
        store = Store()
        store.settings["dynamics"] = values
        store.save()
        print("zapisano w config.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
