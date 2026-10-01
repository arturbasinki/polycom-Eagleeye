#!/usr/bin/env python3
"""Live acceptance session: tracking with voice cues and session recording.

The cues are spoken (spd-say) and shown as a notification, because the person in
front of the camera is not looking at the terminal. The session goes to captures/sessions/*.jsonl -
its measures are computed by tools/replay_session.py.

An interrupt (Ctrl+C, SIGTERM) always stops movement and returns the camera
to its start position.

    .venv/bin/python tools/live_session.py --profile presentation --script presentation
"""

from __future__ import annotations

import argparse
import logging
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eagleeye.config import Store, language_setting  # noqa: E402
from eagleeye.geometry import deg  # noqa: E402
from eagleeye.head_model import dynamics_from_settings  # noqa: E402
from eagleeye.i18n import get_language, set_language, t  # noqa: E402
from eagleeye.tracker import Tracker, TrackerSettings  # noqa: E402
from eagleeye.v4l2 import (CID_PAN_ABSOLUTE, CID_PAN_SPEED, CID_TILT_ABSOLUTE,  # noqa: E402
                           ControlDevice, MjpegStream)

START_DELAY = 5.0
# (seconds, cue): a cue is the tail of a catalog key ``live_session.cue.<cue>``
SCRIPTS = {
    "presentation": [(0, "start"), (5, "stop"), (20, "left"), (27, "stop"),
                     (35, "right"), (45, "stop"), (53, "left_fast"), (59, "stop"),
                     (67, "center"), (74, "stop"), (82, "leave_frame"), (115, "return"),
                     (140, "end")],
    "talk": [(0, "start"), (5, "sit"), (65, "lean_aside"),
             (75, "return"), (95, "stand"), (105, "sit_down"), (125, "end")],
}


class Stop(Exception):
    pass


def _raise_stop(signum, frame):
    raise Stop()


def say(text: str) -> None:
    for cmd in (["notify-send", "-t", "4000", "EagleEye", text], ["spd-say", "-l", get_language(), "-r", "10", text]):
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--profile", default="talk")
    parser.add_argument("--script", default="talk", choices=sorted(SCRIPTS))
    parser.add_argument("--start-pan", type=float, default=35.0, help="degrees; the scan starts from this position")
    parser.add_argument("--device", default="/dev/video0")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    signal.signal(signal.SIGTERM, _raise_stop)
    signal.signal(signal.SIGINT, _raise_stop)

    store = Store()
    set_language(language_setting())
    ctl = ControlDevice(args.device)
    pan0, tilt0 = ctl.get(CID_PAN_ABSOLUTE), ctl.get(CID_TILT_ABSOLUTE)
    stream = MjpegStream(args.device, 1920, 1080)
    stream.start()
    tracker = Tracker(stream, ctl, TrackerSettings(
        profile=args.profile, record=True, dynamics=dynamics_from_settings(store.settings["dynamics"]),
        last_azimuth=(deg(args.start_pan), 0.0)))
    tracker.start()
    cues = list(SCRIPTS[args.script])
    t0 = time.monotonic()
    last = None
    try:
        while True:
            elapsed = time.monotonic() - t0
            while cues and elapsed >= cues[0][0]:
                _, cue = cues.pop(0)
                text = t(f"live_session.cue.{cue}")
                say(text)
                print(f"{elapsed:6.1f}s >>> {text.upper()}", flush=True)
                if cue == "end":
                    raise Stop()
            if not tracker.enabled and elapsed >= START_DELAY:
                tracker.set_enabled(True)
            s = tracker.state
            key = (s.mode, s.pan_state, s.tilt_state, s.moves)
            if tracker.enabled and key != last:
                target = s.target.source if s.target else "-"
                print(f"{elapsed:6.1f}s {s.mode:9s} pan:{s.pan_state:9s} tilt:{s.tilt_state:9s} "
                      f"head {s.pan / 3600:+6.1f}°/{s.tilt / 3600:+5.1f}° target:{target:5s} moves:{s.moves}",
                      flush=True)
                last = key
            time.sleep(0.1)
    except Stop:
        pass
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        tracker.set_enabled(False)
        print(f"moves total: {tracker.state.moves}, speed after disabling: {ctl.get(CID_PAN_SPEED)}", flush=True)
        tracker.move_to(pan=pan0, tilt=tilt0)
        time.sleep(4.0)
        tracker.stop()
        stream.stop()
        ctl.close()
        print("camera returned to the start position", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
