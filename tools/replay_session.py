#!/usr/bin/env python3
"""Odtwarzanie zapisanej sesji w symulatorze z innymi nastawami.

Sesja (captures/sessions/*.jsonl) zawiera pozycje głowy w kątach świata,
niezależne od tego, jak jechała kamera. Symulator odtwarza tę samą osobę
i liczy miary płynności dla wybranego profilu i nadpisań.

    .venv/bin/python tools/replay_session.py captures/sessions/X.jsonl --profile talk --set dwell=1.2
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eagleeye.config import CONFIG_PATH  # noqa: E402
from eagleeye.head_model import dynamics_from_settings  # noqa: E402
from eagleeye.profiles import resolve  # noqa: E402
from eagleeye.sim import SimScene, simulate  # noqa: E402
from eagleeye.tracker import load_session  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("session", type=Path)
    parser.add_argument("--profile", default="talk")
    parser.add_argument("--set", action="append", default=[], metavar="KLUCZ=WARTOŚĆ")
    parser.add_argument("--lag", type=float, default=0.0,
                        help="zwłoka naświetlenia klatki [s] (kamera: ~0,05)")
    parser.add_argument("--jitter", type=float, default=0.0,
                        help="rozrzut zwłoki z klatki na klatkę [s] (nagrania: ~0,02-0,08)")
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()

    rows = load_session(args.session)
    seen = [r for r in rows if r["world"] is not None]
    if len(seen) < 2:
        print("za mało pomiarów w sesji")
        return 1
    t0 = rows[0]["t"]
    ts = np.array([r["t"] - t0 for r in seen])
    pans = np.array([r["world"][0] for r in seen])
    tilts = np.array([r["world"][1] for r in seen])
    present_t = np.array([r["t"] - t0 for r in rows])
    present_v = np.array([r["world"] is not None for r in rows])

    def path(t: float) -> tuple[float, float]:
        return float(np.interp(t, ts, pans)), float(np.interp(t, ts, tilts))

    def present(t: float) -> bool:
        return bool(present_v[min(len(present_v) - 1, int(np.searchsorted(present_t, t)))])

    overrides = dict(kv.split("=", 1) for kv in args.set)
    profile = resolve(args.profile, overrides)
    # Symulujemy kamerę ze zmierzoną dynamiką (jeśli jest w config.json).
    try:
        dyn = dynamics_from_settings(json.loads(CONFIG_PATH.read_text())["settings"].get("dynamics"))
    except (OSError, KeyError, ValueError):
        dyn = dynamics_from_settings(None)
    duration = float(present_t[-1])
    # Podążanie odświeża rozkaz jazdy co takt - liczymy tylko ruszenia z postoju.
    recorded, driving = 0, {"pan": 0, "tilt": 0}
    for row in rows:
        for kind, axis, value in row["cmds"]:
            if kind == "abs":
                recorded += 1
            elif kind == "vel":
                recorded += 1 if value and not driving[axis] else 0
                driving[axis] = value
    scene = SimScene(path, present=present, exposure_lag=args.lag, lag_jitter=args.jitter, seed=args.seed)
    r = simulate(profile, scene, duration, dyn_true=dyn, dyn_model=dyn,
                 start_pan=float(pans[0]))
    print(f"sesja: {duration:.0f} s, nagrane ruszenia/min: {recorded / (duration / 60):.1f}")
    print(f"symulacja ({profile.name}, {overrides or 'bez nadpisań'}):")
    print(f"  ruchy/min      {r.moves_per_min():.2f}  (pan {r.camera.moves_by_axis['pan']}, "
          f"tilt {r.camera.moves_by_axis['tilt']})")
    print(f"  ruszenia/min   {r.motion_starts_per_min():.1f}")
    print(f"  poza strefą    {r.outside_fraction(profile):.1%}")
    print(f"  przerwane/min  {r.interrupted_per_min():.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
