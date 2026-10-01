#!/usr/bin/env python3
"""Frame statistics from a recorded session (captures/sessions/*.jsonl) - for calibrating thresholds.

Prints the yaw distribution (how much time |yaw| is in each bucket), the head scale in degrees,
side changes and zoom moves. Without an argument - the newest session.

    .venv/bin/python tools/framing_stats.py [path.jsonl]
"""

from __future__ import annotations

import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eagleeye.config import captures_dir  # noqa: E402
from eagleeye.tracker import load_session  # noqa: E402

BINS = (0.0, 0.1, 0.2, 0.35, 0.5, 0.75, 1.01)


def main() -> int:
    if len(sys.argv) > 1:
        path = Path(sys.argv[1])
    else:
        sessions = sorted((captures_dir() / "sessions").glob("*.jsonl"))
        if not sessions:
            print("no sessions in captures/sessions/")
            return 1
        path = sessions[-1]
    rows = load_session(path)
    print(f"session: {path.name}, rows: {len(rows)}")
    yaws = [abs(r["yaw"]) for r in rows if r.get("yaw") is not None]
    if yaws:
        print("|yaw|:")
        for lo, hi in zip(BINS, BINS[1:]):
            n = sum(1 for y in yaws if lo <= y < hi)
            print(f"  {lo:4.2f}-{hi:4.2f}: {n / len(yaws):6.1%}")
    scales = [r["head_scale"] / 3600.0 for r in rows if r.get("head_scale")]
    if scales:
        print(f"head scale [°]: median {statistics.median(scales):.2f}, "
              f"min {min(scales):.2f}, max {max(scales):.2f}")
    sides = [r.get("side") for r in rows if r.get("side")]
    changes = sum(1 for a, b in zip(sides, sides[1:]) if a != b)
    print(f"side changes: {changes}")
    zooms = [c for r in rows for c in r.get("cmds", []) if c[0] == "zoom"]
    print(f"zoom commands: {len(zooms)} -> {[int(c[2]) for c in zooms]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
