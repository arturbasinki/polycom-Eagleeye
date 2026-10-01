#!/usr/bin/env python3
"""Identifying pan and tilt absolute movement: the full trajectory, not just start and end.

``measure_dynamics.py`` measures only pan and only the start/end of the movement, while the head model
uses the same parameters for tilt. The model is needed at *every* moment of the movement:
the target world angle = camera angle at the frame moment (from the model) + the shift in pixels.
A model error while moving goes straight into the target measurement - the measurement "runs away" in the
direction of travel, the director sees a target that is moving and adds movement (catch-up in steps, oscillation).

For every axis and several distances the tool records the angle from phase correlation of consecutive
frames (time = V4L2 buffer timestamp, the same one the tracker uses), and then fits the
model parameters (latency, base time, speed, shape ``nu``) by least
squares over whole runs. It prints the error of the current and the fitted model.

    .venv/bin/python tools/measure_trajectory.py           # print only
    .venv/bin/python tools/measure_trajectory.py --save    # save to config.json

The camera must be free (application closed), the frame must have texture. The position and zoom are restored.

The calibration of this camera is in the code (``head_model.Dynamics`` defaults) and does not
disappear with ``config.json``. ``--save`` writes the result as an override in ``config.json``
(e.g. for another unit); write the new calibration of this unit into ``Dynamics``.
"""

from __future__ import annotations

import argparse
import itertools
import json
import signal
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eagleeye.config import Store  # noqa: E402
from eagleeye.detectors import decode_mjpeg  # noqa: E402
from eagleeye.geometry import View, deg  # noqa: E402
from eagleeye.head_model import Dynamics, dynamics_from_settings  # noqa: E402
from eagleeye.motion import s_curve  # noqa: E402
from eagleeye.v4l2 import (CID_PAN_ABSOLUTE, CID_PAN_SPEED, CID_TILT_ABSOLUTE,  # noqa: E402
                           CID_TILT_SPEED, CID_ZOOM_ABSOLUTE, ControlDevice, MjpegStream)

W, H = 640, 360
DISTANCES_DEG = (2, 5, 10, 20)
CTRL = {"pan": CID_PAN_ABSOLUTE, "tilt": CID_TILT_ABSOLUTE}
RECORD_S = 2.6


class Probe:
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

    def record(self, axis: str, seconds: float, action) -> tuple[float, np.ndarray, np.ndarray]:
        """(command moment, frame times, accumulated axis angle [arcsec, without direction sign])."""
        ts, prev = self._gray()
        samples = [(ts, 0.0)]
        total = 0.0
        fired = None
        t0 = time.monotonic()
        while time.monotonic() - t0 < seconds:
            if fired is None and time.monotonic() - t0 >= 0.3:
                fired = time.monotonic()
                action()
            ts, cur = self._gray()
            (dx, dy), response = cv2.phaseCorrelate(prev, cur, self.window)
            prev = cur
            if response > 0.03:
                total += (-dx if axis == "pan" else dy) * self.scale
            samples.append((ts, total))
        t = np.array([s[0] for s in samples])
        x = np.array([s[1] for s in samples])
        return fired, t, x


def model_path(tau: np.ndarray, d: float, lat: float, base: float, speed: float, nu: float) -> np.ndarray:
    dur = base + abs(d) / speed
    out = np.empty_like(tau)
    for i, s in enumerate(tau):
        f = (s - lat) / dur
        out[i] = 0.0 if f <= 0 else (1.0 if f >= 1 else s_curve(f, nu))
    return out * d


def rms(runs, lat, base, speed, nu) -> float:
    """RMS error [arcsec] of the shape over time. The run is normalized to the final angle:
    phase correlation of the whole frame overstates the angle by ~10% (lens distortion), and what
    matters here is *when* the head is at a given part of the path - that decides the target measurement error while moving."""
    err = np.concatenate([(x - model_path(tau, d, lat, base, speed, nu) / d) * d for d, tau, x in runs])
    return float(np.sqrt(np.mean(err ** 2)))


def fit(runs, start: Dynamics) -> tuple[dict, float]:
    best = (rms(runs, start.abs_latency, start.abs_base, start.abs_speed, start.abs_nu),
            start.abs_latency, start.abs_base, start.abs_speed, start.abs_nu)
    # Coarse grid, then refinement around the best point.
    grids = {
        "lat": np.linspace(0.0, 0.4, 9), "base": np.linspace(0.1, 1.0, 10),
        "speed": np.array([deg(v) for v in (20, 30, 45, 60, 80, 110, 150)]),
        "nu": np.array([1.0, 2.0, 3.0, 5.0, 10.0]),
    }
    for _ in range(4):
        for lat, base, speed, nu in itertools.product(grids["lat"], grids["base"], grids["speed"], grids["nu"]):
            e = rms(runs, lat, base, speed, nu)
            if e < best[0]:
                best = (e, lat, base, speed, nu)
        _, lat, base, speed, nu = best
        grids = {
            "lat": np.clip(np.linspace(lat - 0.04, lat + 0.04, 5), 0.0, None),
            "base": np.clip(np.linspace(base - 0.08, base + 0.08, 5), 0.02, None),
            "speed": np.linspace(speed * 0.8, speed * 1.2, 5),
            "nu": np.clip(np.linspace(nu - 1.0, nu + 1.0, 5), 0.5, None),
        }
    e, lat, base, speed, nu = best
    return {"abs_latency": float(lat), "abs_base": float(base), "abs_speed": float(speed), "abs_nu": float(nu)}, e


def measure_axis(probe: Probe, ctl: ControlDevice, axis: str, start: Dynamics) -> tuple[dict, list]:
    cid = CTRL[axis]
    home = ctl.get(cid)
    lo, hi = ctl.control(cid).minimum, ctl.control(cid).maximum
    runs = []
    for d_deg in DISTANCES_DEG:
        for sign in (1, -1):
            d = sign * deg(d_deg)
            if not lo <= home + d <= hi:
                continue
            fired, t, x = probe.record(axis, RECORD_S, lambda tg=int(home + d): ctl.set(cid, tg))
            tau = t - fired
            x = x - np.interp(0.0, tau, x)          # angle relative to the command moment
            moved = x[-1]
            runs.append((float(abs(d)), tau, x * (1 if d > 0 else -1) * np.sign(moved or 1) * np.sign(d)))
            print(f"  {axis} {d / 3600:+5.0f}°: measured angle {abs(moved) / 3600:5.1f}°  "
                  f"(scale {abs(moved) / abs(d):.3f})")
            ctl.set(cid, int(home))
            time.sleep(2.2)
    # The image axis direction does not matter - we measure progress toward the target, normalized to
    # the end. Short moves (2°) and runs with a failed correlation (end outside 0.8-1.4 of the commanded)
    # are skipped - the correlation noise there is larger than the signal.
    clean = []
    for d, tau, x in runs:
        x = np.abs(x)
        end = float(np.median(x[tau > RECORD_S - 0.6]))
        if d >= deg(4) and 0.8 < end / d < 1.4:
            clean.append((d, tau, x / end))
    runs = clean
    now = rms(runs, start.abs_latency, start.abs_base, start.abs_speed, start.abs_nu)
    params, err = fit(runs, start)
    print(f"  {axis}: RMS error of the current model {now / 3600:.2f}°, fitted {err / 3600:.2f}°")
    print(f"  {axis}: latency {params['abs_latency']:.3f} s, base {params['abs_base']:.3f} s, "
          f"speed {params['abs_speed'] / 3600:.1f}°/s, nu {params['abs_nu']:.2f}")
    return params, runs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--device", default="/dev/video0")
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--dump", type=Path, help="save the raw runs (JSON)")
    args = parser.parse_args()

    store = Store()
    start = dynamics_from_settings(store.settings.get("dynamics"))
    ctl = ControlDevice(args.device)
    stream = MjpegStream(args.device, W, H)
    stream.start()
    pan0, tilt0, zoom0 = ctl.get(CID_PAN_ABSOLUTE), ctl.get(CID_TILT_ABSOLUTE), ctl.get(CID_ZOOM_ABSOLUTE)

    def restore(*_):
        ctl.set(CID_PAN_SPEED, 0)
        ctl.set(CID_TILT_SPEED, 0)
        ctl.set(CID_PAN_ABSOLUTE, int(pan0))
        ctl.set(CID_TILT_ABSOLUTE, int(tilt0))
        ctl.set(CID_ZOOM_ABSOLUTE, int(zoom0))

    signal.signal(signal.SIGTERM, lambda *_: (restore(), sys.exit(1)))
    result, dump = {}, {}
    try:
        ctl.set(CID_ZOOM_ABSOLUTE, 0)
        time.sleep(2.0)
        probe = Probe(stream)
        for axis in ("pan", "tilt"):
            print(f"absolute movement ({axis}):")
            result[axis], runs = measure_axis(probe, ctl, axis, start)
            dump[axis] = [(d, tau.tolist(), x.tolist()) for d, tau, x in runs]
    finally:
        restore()
        time.sleep(2.0)
        stream.stop()
        ctl.close()
    if args.dump:
        args.dump.write_text(json.dumps(dump))
    if args.save:
        # We save only tilt: pan has parameters from measure_dynamics.py confirmed in acceptance,
        # and fitting here improves them only slightly (0.41° -> 0.33° RMS, 2026-09-26).
        dyn = dict(store.settings.get("dynamics") or {})
        dyn.update({"tilt_" + k: v for k, v in result["tilt"].items()})
        store.settings["dynamics"] = dyn
        store.save()
        print("saved in config.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
