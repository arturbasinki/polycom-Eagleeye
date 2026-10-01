"""Test double for ControlDevice: remembers values and every write, without hardware."""

from __future__ import annotations

from eagleeye.detectors import Detection
from eagleeye.perception import Observation
from eagleeye.v4l2 import (CID_PAN_ABSOLUTE, CID_PAN_SPEED, CID_TILT_ABSOLUTE,
                           CID_TILT_SPEED, CID_ZOOM_ABSOLUTE, CID_ZOOM_CONTINUOUS, Control,
                           V4L2Error)

RANGES = {
    CID_PAN_ABSOLUTE: (-612000, 612000),
    CID_TILT_ABSOLUTE: (-108000, 324000),
    CID_PAN_SPEED: (-24, 24),
    CID_TILT_SPEED: (-20, 20),
    CID_ZOOM_ABSOLUTE: (0, 5680),
    CID_ZOOM_CONTINUOUS: (-7, 7),
}


class FakeControls:
    def __init__(self, **initial: int) -> None:
        self.values = {cid: 0 for cid in RANGES}
        self.values.update({int(k[1:], 16) if k.startswith("x") else k: v for k, v in initial.items()})
        self.writes: list[tuple[int, int]] = []
        self.fail_writes = False

    def control(self, ctrl_id: int) -> Control | None:
        if ctrl_id not in RANGES:
            return None
        lo, hi = RANGES[ctrl_id]
        return Control(id=ctrl_id, name=str(ctrl_id), type=1, minimum=lo, maximum=hi,
                       step=1, default=0, flags=0)

    def get(self, ctrl_id: int) -> int:
        if ctrl_id not in self.values:
            raise V4L2Error("no such control")
        return self.values[ctrl_id]

    def set(self, ctrl_id: int, value: int) -> int:
        if self.fail_writes:
            raise V4L2Error("S_EXT_CTRLS: No such device")
        self.values[ctrl_id] = int(value)
        self.writes.append((ctrl_id, int(value)))
        return int(value)

    def writes_to(self, ctrl_id: int) -> list[int]:
        return [v for c, v in self.writes if c == ctrl_id]

    def capabilities(self) -> dict:
        return {"driver": "atrapa", "card": "Atrapa kamery", "bus_info": "usb-atrapa",
                "version": 0, "capabilities": 0, "device_caps": 1, "is_capture": True}

    def close(self) -> None:
        self.closed = True


class FakeCameraStream:
    """Test double for MjpegStream: a constant JPEG frame, a new one every 1/30 s."""

    def __init__(self, path: str = "/dev/video0", width: int = 640, height: int = 360) -> None:
        import time

        import cv2
        import numpy as np
        ok, buf = cv2.imencode(".jpg", np.full((height, width, 3), 90, np.uint8))
        self.jpg = buf.tobytes()
        self.actual_width, self.actual_height = width, height
        self.dropped = 0
        self.started = self.stopped = False
        self._time = time

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def frame_timed(self, last_id: int = 0, timeout: float = 2.0):
        self._time.sleep(min(timeout, 1 / 30))
        return last_id + 1, self.jpg, self._time.monotonic()

    def frame(self, last_id: int = 0, timeout: float = 2.0):
        frame_id, data, _ = self.frame_timed(last_id, timeout)
        return frame_id, data


class TwoPeople:
    """Two standing people, coordinates in the frame after half-scale decoding (min. 320x180).
    ``observe`` works like Perception in automatic mode - it returns the bigger person;
    ``observation`` as on selection."""

    last_ms = 0.0
    description = "atrapa"

    def __init__(self) -> None:
        self.left = Detection(40, 20, 50, 140, 0.9, "poza")        # the bigger one
        self.right = Detection(200, 20, 45, 130, 0.9, "poza")
        self.dets = [self.left, self.right]
        self.fail_observation = False

    @staticmethod
    def _obs(det: Detection, t: float) -> Observation:
        return Observation(det.x + det.w / 2, float(det.y), t, det.score, det.label, det.as_box())

    def observe(self, frame, t, previous):
        big = max(self.dets, key=lambda d: d.area) if self.dets else None
        return (None if big is None else self._obs(big, t)), list(self.dets)

    def observation(self, det: Detection, t: float) -> Observation:
        if self.fail_observation:
            raise RuntimeError("selection failure")
        return self._obs(det, t)
