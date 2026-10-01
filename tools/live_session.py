#!/usr/bin/env python3
"""Sesja odbiorcza na żywo: śledzenie z komendami głosowymi i zapisem sesji.

Komendy są mówione (spd-say) i pokazywane jako powiadomienie, bo osoba przed
kamerą nie patrzy w terminal. Sesja trafia do captures/sessions/*.jsonl -
miary liczy tools/replay_session.py.

Przerwanie (Ctrl+C, SIGTERM) zawsze kończy się zatrzymaniem ruchu i powrotem
kamery na pozycję startową.

    .venv/bin/python tools/live_session.py --profile prezentacja --script prezentacja
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

from eagleeye.config import Store  # noqa: E402
from eagleeye.geometry import deg  # noqa: E402
from eagleeye.head_model import dynamics_from_settings  # noqa: E402
from eagleeye.tracker import Tracker, TrackerSettings  # noqa: E402
from eagleeye.v4l2 import (CID_PAN_ABSOLUTE, CID_PAN_SPEED, CID_TILT_ABSOLUTE,  # noqa: E402
                           ControlDevice, MjpegStream)

START_DELAY = 5.0
SCRIPTS = {
    "prezentacja": [(0, "start za pięć sekund"), (5, "stój"), (20, "idź w lewo"), (27, "stój"),
                    (35, "idź w prawo"), (45, "stój"), (53, "idź w lewo szybko"), (59, "stój"),
                    (67, "wróć na środek"), (74, "stój"), (82, "wyjdź z kadru"), (115, "wróć"),
                    (140, "koniec")],
    "rozmowa": [(0, "start za pięć sekund"), (5, "siedź normalnie"), (65, "odchyl się w bok"),
                (75, "wróć"), (95, "wstań"), (105, "usiądź"), (125, "koniec")],
}


class Stop(Exception):
    pass


def _raise_stop(signum, frame):
    raise Stop()


def say(text: str) -> None:
    for cmd in (["notify-send", "-t", "4000", "EagleEye", text], ["spd-say", "-l", "pl", "-r", "10", text]):
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--profile", default="rozmowa")
    parser.add_argument("--script", default="rozmowa", choices=sorted(SCRIPTS))
    parser.add_argument("--start-pan", type=float, default=35.0, help="stopnie; od tego miejsca startuje skan")
    parser.add_argument("--device", default="/dev/video0")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    signal.signal(signal.SIGTERM, _raise_stop)
    signal.signal(signal.SIGINT, _raise_stop)

    store = Store()
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
            t = time.monotonic() - t0
            while cues and t >= cues[0][0]:
                _, text = cues.pop(0)
                say(text)
                print(f"{t:6.1f}s >>> {text.upper()}", flush=True)
                if text == "koniec":
                    raise Stop()
            if not tracker.enabled and t >= START_DELAY:
                tracker.set_enabled(True)
            s = tracker.state
            key = (s.mode, s.pan_state, s.tilt_state, s.moves)
            if tracker.enabled and key != last:
                target = s.target.source if s.target else "-"
                print(f"{t:6.1f}s {s.mode:9s} pan:{s.pan_state:9s} tilt:{s.tilt_state:9s} "
                      f"głowica {s.pan / 3600:+6.1f}°/{s.tilt / 3600:+5.1f}° cel:{target:5s} ruchów:{s.moves}",
                      flush=True)
                last = key
            time.sleep(0.1)
    except Stop:
        pass
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        tracker.set_enabled(False)
        print(f"ruchów łącznie: {tracker.state.moves}, prędkość po wyłączeniu: {ctl.get(CID_PAN_SPEED)}", flush=True)
        tracker.move_to(pan=pan0, tilt=tilt0)
        time.sleep(4.0)
        tracker.stop()
        stream.stop()
        ctl.close()
        print("kamera wróciła na pozycję startową", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
