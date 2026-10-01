"""V4L2 access layer for the Polycom EagleEye IV USB camera.

Two independent paths, deliberately on separate file descriptors:

* :class:`MjpegStream` - the frame-grabbing thread (mmap + streaming).
* :class:`ControlDevice` - control reads and writes (does not interfere with the stream).

Notes on the layout of the structures that are easy to get wrong:

* ``struct v4l2_format`` has the ``fmt`` union at offset **8**, not 4 - the union contains
  a pointer, so it is aligned to 8 bytes. In our ``raw`` buffer (which
  starts at offset 4 of the structure) ``v4l2_pix_format`` therefore sits at offset 4.
* ``struct v4l2_ext_control`` is **20 bytes** - the union is ``__packed``, so there is
  no padding to 24. We reproduce that explicitly with the ``_pad`` field, without ``_pack_``,
  to avoid deprecation and keep the natural 4-byte alignment.
* The deprecated ``VIDIOC_G_CTRL``/``S_CTRL`` return ``ENOTTY`` on uvcvideo;
  we use ``VIDIOC_G_EXT_CTRLS``/``S_EXT_CTRLS``.
"""

from __future__ import annotations

import ctypes
import errno
import fcntl
import mmap
import os
import select
import struct
import threading
import time
from dataclasses import dataclass

BUF_TYPE_VIDEO_CAPTURE = 1
BUF_TYPE_VIDEO_CAPTURE_MPLANE = 9
BUF_TYPE_VIDEO_OUTPUT = 2
MEMORY_MMAP = 1
FIELD_NONE = 1
PIX_FMT_YUV420 = b"YU12"    # I420: Y, then U and V at quarter resolution
PIX_OFF = 4  # offset of struct v4l2_pix_format inside our "raw" buffer

CTRL_FLAG_NEXT_CTRL = 0x80000000
CTRL_FLAG_DISABLED = 0x00000001
CTRL_TYPE_CTRL_CLASS = 6
WHICH_CUR_VAL = 0
WHICH_DEF_VAL = 0x0F000000

# Control codes we use in the interface
CID_BRIGHTNESS = 0x00980900
CID_CONTRAST = 0x00980901
CID_SATURATION = 0x00980902
CID_HUE = 0x00980903
CID_WHITE_BALANCE_AUTO = 0x0098090C
CID_GAMMA = 0x00980910
CID_POWER_LINE_FREQ = 0x00980918
CID_WHITE_BALANCE_TEMP = 0x0098091A
CID_SHARPNESS = 0x0098091B
CID_BACKLIGHT_COMP = 0x0098091C
CID_PAN_ABSOLUTE = 0x009A0908
CID_TILT_ABSOLUTE = 0x009A0909
CID_FOCUS_ABSOLUTE = 0x009A090A
CID_FOCUS_AUTO = 0x009A090C
CID_ZOOM_ABSOLUTE = 0x009A090D
CID_ZOOM_CONTINUOUS = 0x009A090F
CID_PAN_SPEED = 0x009A0920
CID_TILT_SPEED = 0x009A0921


def _IOC(direction: int, typ: str, nr: int, size: int) -> int:
    return (direction << 30) | (size << 16) | (ord(typ) << 8) | nr


def _IOR(typ: str, nr: int, size: int) -> int:
    return _IOC(2, typ, nr, size)


def _IOWR(typ: str, nr: int, size: int) -> int:
    return _IOC(3, typ, nr, size)


def _IOW(typ: str, nr: int, size: int) -> int:
    return _IOC(1, typ, nr, size)


class V4L2Format(ctypes.Structure):
    """struct v4l2_format - size 208, the pix field at offset 8 of the structure."""

    _fields_ = [("type", ctypes.c_uint32), ("raw", ctypes.c_uint8 * 204)]


class V4L2Requestbuffers(ctypes.Structure):
    _fields_ = [
        ("count", ctypes.c_uint32),
        ("type", ctypes.c_uint32),
        ("memory", ctypes.c_uint32),
        ("capabilities", ctypes.c_uint32),
        ("reserved", ctypes.c_uint32 * 1),
    ]


class _Timeval(ctypes.Structure):
    _fields_ = [("tv_sec", ctypes.c_long), ("tv_usec", ctypes.c_long)]


# A timestamp that differs from the reception moment by more than this many seconds is
# treated as unreliable (a driver without a timestamp or a clock other than CLOCK_MONOTONIC).
MAX_TS_SKEW = 1.0


def timeval_seconds(tv: _Timeval) -> float:
    """The V4L2 buffer timestamp in seconds (uvcvideo: CLOCK_MONOTONIC)."""
    return tv.tv_sec + tv.tv_usec / 1_000_000.0


def frame_time(ts: float, now: float, max_skew: float = MAX_TS_SKEW) -> float:
    """Frame time: the buffer timestamp, unless it is implausible - then the reception moment.

    The tracker converts the target position through the head angle at the moment the frame
    was captured, so a timestamp from another clock (e.g. from hours ago) would ruin every measurement.
    """
    return ts if 0.0 <= now - ts < max_skew else now


class _Timecode(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_uint8),
        ("flags", ctypes.c_uint8),
        ("frames", ctypes.c_uint8),
        ("seconds", ctypes.c_uint8),
        ("minutes", ctypes.c_uint8),
        ("hours", ctypes.c_uint8),
        ("userbits", ctypes.c_uint8 * 4),
    ]


class _OffsetUnion(ctypes.Union):
    _fields_ = [
        ("offset", ctypes.c_uint32),
        ("userptr", ctypes.c_ulong),
        ("planes", ctypes.c_void_p),
        ("fd", ctypes.c_int32),
    ]


class _TailUnion(ctypes.Union):
    _fields_ = [("request_fd", ctypes.c_int32), ("reserved", ctypes.c_uint32)]


class V4L2Buffer(ctypes.Structure):
    """struct v4l2_buffer - size 88 on 64-bit."""

    _fields_ = [
        ("index", ctypes.c_uint32),
        ("type", ctypes.c_uint32),
        ("bytesused", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("field", ctypes.c_uint32),
        ("timestamp", _Timeval),
        ("timecode", _Timecode),
        ("sequence", ctypes.c_uint32),
        ("memory", ctypes.c_uint32),
        ("m", _OffsetUnion),
        ("length", ctypes.c_uint32),
        ("reserved2", ctypes.c_uint32),
        ("tail", _TailUnion),
    ]


class V4L2ExtControl(ctypes.Structure):
    """struct v4l2_ext_control - 20 bytes, ``value`` at offset 12.

    Field order straight from ``/usr/include/linux/videodev2.h``::

        __u32 id;             // 0
        __u32 size;           // 4
        __u32 reserved2[1];   // 8
        union { __s32 value; ... } __attribute__((packed));   // 12

    The union is ``packed``, so the whole thing is 20 bytes without padding to 24.
    We reproduce that with the natural 4-byte alignment - without ``_pack_``, so we do not
    hit Python deprecation. We only handle scalar controls;
    pointer controls (``string``/``ptr``) would need the union at offset 12.
    """

    _fields_ = [
        ("id", ctypes.c_uint32),
        ("size", ctypes.c_uint32),
        ("reserved2", ctypes.c_uint32),
        ("value", ctypes.c_int32),
        ("_pad", ctypes.c_uint32),
    ]


class V4L2ExtControls(ctypes.Structure):
    _fields_ = [
        ("which", ctypes.c_uint32),
        ("count", ctypes.c_uint32),
        ("error_idx", ctypes.c_uint32),
        ("request_fd", ctypes.c_int32),
        ("reserved", ctypes.c_uint32 * 1),
        ("controls", ctypes.POINTER(V4L2ExtControl)),
    ]


class V4L2QueryCtrl(ctypes.Structure):
    _fields_ = [
        ("id", ctypes.c_uint32),
        ("type", ctypes.c_uint32),
        ("name", ctypes.c_char * 32),
        ("minimum", ctypes.c_int32),
        ("maximum", ctypes.c_int32),
        ("step", ctypes.c_int32),
        ("default_value", ctypes.c_int32),
        ("flags", ctypes.c_uint32),
        ("reserved", ctypes.c_uint32 * 2),
    ]


class V4L2Capability(ctypes.Structure):
    _fields_ = [
        ("driver", ctypes.c_char * 16),
        ("card", ctypes.c_char * 32),
        ("bus_info", ctypes.c_char * 32),
        ("version", ctypes.c_uint32),
        ("capabilities", ctypes.c_uint32),
        ("device_caps", ctypes.c_uint32),
        ("reserved", ctypes.c_uint32 * 3),
    ]


VIDIOC_QUERYCAP = _IOR("V", 0, ctypes.sizeof(V4L2Capability))
VIDIOC_S_FMT = _IOWR("V", 5, ctypes.sizeof(V4L2Format))
VIDIOC_G_FMT = _IOWR("V", 4, ctypes.sizeof(V4L2Format))
VIDIOC_REQBUFS = _IOWR("V", 8, ctypes.sizeof(V4L2Requestbuffers))
VIDIOC_QUERYBUF = _IOWR("V", 9, ctypes.sizeof(V4L2Buffer))
VIDIOC_QBUF = _IOWR("V", 15, ctypes.sizeof(V4L2Buffer))
VIDIOC_DQBUF = _IOWR("V", 17, ctypes.sizeof(V4L2Buffer))
VIDIOC_STREAMON = _IOW("V", 18, 4)
VIDIOC_STREAMOFF = _IOW("V", 19, 4)
VIDIOC_QUERYCTRL = _IOWR("V", 36, ctypes.sizeof(V4L2QueryCtrl))
VIDIOC_G_EXT_CTRLS = _IOWR("V", 71, ctypes.sizeof(V4L2ExtControls))
VIDIOC_S_EXT_CTRLS = _IOWR("V", 72, ctypes.sizeof(V4L2ExtControls))

assert ctypes.sizeof(V4L2Format) == 208, ctypes.sizeof(V4L2Format)
assert ctypes.sizeof(V4L2Buffer) == 88, ctypes.sizeof(V4L2Buffer)
assert ctypes.sizeof(V4L2ExtControl) == 20, ctypes.sizeof(V4L2ExtControl)
assert ctypes.sizeof(V4L2ExtControls) == 32, ctypes.sizeof(V4L2ExtControls)
assert ctypes.sizeof(V4L2QueryCtrl) == 68, ctypes.sizeof(V4L2QueryCtrl)


@dataclass(frozen=True)
class Control:
    """A single V4L2 control together with its limits."""

    id: int
    name: str
    type: int
    minimum: int
    maximum: int
    step: int
    default: int
    flags: int

    @property
    def readonly(self) -> bool:
        return bool(self.flags & 0x00000004)  # V4L2_CTRL_FLAG_READ_ONLY


def open_device(path: str) -> int:
    return os.open(path, os.O_RDWR | os.O_NONBLOCK)


class V4L2Error(RuntimeError):
    pass


class ControlDevice:
    """Control reads and writes. Opens its own descriptor, so it does not disturb the stream."""

    def __init__(self, path: str = "/dev/video0") -> None:
        self.path = path
        self._fd = open_device(path)
        self._lock = threading.Lock()
        self._cache: dict[int, Control] | None = None

    def close(self) -> None:
        if self._fd >= 0:
            os.close(self._fd)
            self._fd = -1

    def __enter__(self) -> ControlDevice:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # --- device information ---

    def capabilities(self) -> dict:
        cap = V4L2Capability()
        fcntl.ioctl(self._fd, VIDIOC_QUERYCAP, cap)
        return {
            "driver": cap.driver.decode(errors="replace"),
            "card": cap.card.decode(errors="replace"),
            "bus_info": cap.bus_info.decode(errors="replace"),
            "version": cap.version,
            "capabilities": cap.capabilities,
            "device_caps": cap.device_caps,
            "is_capture": bool(cap.device_caps & 0x00000001),
        }

    # --- controls ---

    def list_controls(self) -> list[Control]:
        """All controls except the class headers."""
        if self._cache is None:
            controls: list[Control] = []
            qc = V4L2QueryCtrl()
            qc.id = CTRL_FLAG_NEXT_CTRL
            while True:
                try:
                    fcntl.ioctl(self._fd, VIDIOC_QUERYCTRL, qc)
                except OSError:
                    break
                if qc.type != CTRL_TYPE_CTRL_CLASS and not (qc.flags & CTRL_FLAG_DISABLED):
                    controls.append(
                        Control(
                            id=qc.id,
                            name=qc.name.split(b"\0")[0].decode(errors="replace"),
                            type=qc.type,
                            minimum=qc.minimum,
                            maximum=qc.maximum,
                            step=qc.step,
                            default=qc.default_value,
                            flags=qc.flags,
                        )
                    )
                qc.id |= CTRL_FLAG_NEXT_CTRL
            self._cache = controls
        return list(self._cache)

    def control(self, ctrl_id: int) -> Control | None:
        for c in self.list_controls():
            if c.id == ctrl_id:
                return c
        return None

    def get(self, ctrl_id: int, which: int = WHICH_CUR_VAL) -> int:
        ctl = V4L2ExtControl()
        ctl.id = ctrl_id
        ctl.size = 0
        ctrls = V4L2ExtControls()
        ctrls.which = which
        ctrls.count = 1
        ctrls.controls = ctypes.pointer(ctl)
        with self._lock:
            if self._fd < 0:
                raise V4L2Error(f"device {self.path} is closed")
            try:
                fcntl.ioctl(self._fd, VIDIOC_G_EXT_CTRLS, ctrls)
            except OSError as e:
                raise V4L2Error(f"G_EXT_CTRLS 0x{ctrl_id:08x}: {e.strerror}") from e
        return ctl.value

    def set(self, ctrl_id: int, value: int) -> int:
        """Sets a control and returns the value confirmed by the device."""
        ctl = V4L2ExtControl()
        ctl.id = ctrl_id
        ctl.size = 0
        ctl.value = int(value)
        ctrls = V4L2ExtControls()
        ctrls.which = WHICH_CUR_VAL
        ctrls.count = 1
        ctrls.controls = ctypes.pointer(ctl)
        with self._lock:
            if self._fd < 0:
                raise V4L2Error(f"device {self.path} is closed")
            try:
                fcntl.ioctl(self._fd, VIDIOC_S_EXT_CTRLS, ctrls)
            except OSError as e:
                raise V4L2Error(f"S_EXT_CTRLS 0x{ctrl_id:08x}={value}: {e.strerror}") from e
        return ctl.value

    def get_many(self, ctrl_ids: list[int]) -> dict[int, int]:
        """Reading many controls in a single call."""
        if not ctrl_ids:
            return {}
        arr = (V4L2ExtControl * len(ctrl_ids))()
        for i, cid in enumerate(ctrl_ids):
            arr[i].id = cid
            arr[i].size = 0
        ctrls = V4L2ExtControls()
        ctrls.which = WHICH_CUR_VAL
        ctrls.count = len(ctrl_ids)
        ctrls.controls = ctypes.cast(arr, ctypes.POINTER(V4L2ExtControl))
        with self._lock:
            if self._fd < 0:
                raise V4L2Error(f"device {self.path} is closed")
            fcntl.ioctl(self._fd, VIDIOC_G_EXT_CTRLS, ctrls)
        return {arr[i].id: arr[i].value for i in range(len(ctrl_ids))}


class MjpegStream:
    """The MJPEG grabbing thread. Always exposes the last complete frame.

    Frames are passed as raw JPEG bytes - without recompression. The first
    frames after the stream starts are sometimes truncated (no EOI marker), so
    we drop incomplete JPEGs.
    """

    def __init__(self, path: str = "/dev/video0", width: int = 1280, height: int = 720,
                 buffers: int = 4) -> None:
        self.path = path
        self.width = width
        self.height = height
        self.buffers = buffers
        self._fd = -1
        self._maps: list[mmap.mmap] = []
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._frame: bytes | None = None
        self._frame_id = 0
        self._frame_ts = 0.0
        self._dropped = 0
        self.error: str | None = None
        self.actual_width = 0
        self.actual_height = 0

    def start(self) -> None:
        self._fd = open_device(self.path)
        fmt = V4L2Format()
        fmt.type = BUF_TYPE_VIDEO_CAPTURE
        struct.pack_into("=II", fmt.raw, PIX_OFF, self.width, self.height)
        fmt.raw[PIX_OFF + 8:PIX_OFF + 12] = b"MJPG"
        struct.pack_into("=I", fmt.raw, PIX_OFF + 12, FIELD_NONE)
        fcntl.ioctl(self._fd, VIDIOC_S_FMT, fmt)
        self.actual_width, self.actual_height = struct.unpack_from("=II", fmt.raw, PIX_OFF)
        fourcc = bytes(fmt.raw[PIX_OFF + 8:PIX_OFF + 12]).decode("ascii", "replace")
        if fourcc != "MJPG":
            raise V4L2Error(f"the camera did not accept the MJPG format (got {fourcc!r})")

        req = V4L2Requestbuffers()
        req.count = self.buffers
        req.type = BUF_TYPE_VIDEO_CAPTURE
        req.memory = MEMORY_MMAP
        fcntl.ioctl(self._fd, VIDIOC_REQBUFS, req)
        if req.count < 2:
            raise V4L2Error(f"too few buffers: {req.count}")

        for i in range(req.count):
            buf = V4L2Buffer()
            buf.type = BUF_TYPE_VIDEO_CAPTURE
            buf.memory = MEMORY_MMAP
            buf.index = i
            fcntl.ioctl(self._fd, VIDIOC_QUERYBUF, buf)
            self._maps.append(
                mmap.mmap(self._fd, buf.length, prot=mmap.PROT_READ | mmap.PROT_WRITE,
                          flags=mmap.MAP_SHARED, offset=buf.m.offset)
            )
            fcntl.ioctl(self._fd, VIDIOC_QBUF, buf)

        fcntl.ioctl(self._fd, VIDIOC_STREAMON, struct.pack("=I", BUF_TYPE_VIDEO_CAPTURE))
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="mjpeg-stream", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                r, _, _ = select.select([self._fd], [], [], 0.5)
                if not r:
                    continue
                buf = V4L2Buffer()
                buf.type = BUF_TYPE_VIDEO_CAPTURE
                buf.memory = MEMORY_MMAP
                fcntl.ioctl(self._fd, VIDIOC_DQBUF, buf)
                data = bytes(self._maps[buf.index][:buf.bytesused])
                ts = timeval_seconds(buf.timestamp)
                fcntl.ioctl(self._fd, VIDIOC_QBUF, buf)
            except OSError as e:
                if e.errno in (errno.EAGAIN, errno.EINTR):
                    continue
                self.error = str(e)
                time.sleep(0.2)
                continue

            if len(data) > 1000 and data[:2] == b"\xff\xd8" and data[-2:] == b"\xff\xd9":
                stamp = frame_time(ts, time.monotonic())
                with self._lock:
                    self._frame = data
                    self._frame_id += 1
                    self._frame_ts = stamp
            else:
                self._dropped += 1

    def frame_timed(self, last_id: int = 0, timeout: float = 2.0) -> tuple[int, bytes | None, float]:
        """Waits for a frame newer than ``last_id``. Returns (id, bytes, capture time)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                if self._frame_id > last_id and self._frame is not None:
                    return self._frame_id, self._frame, self._frame_ts
            time.sleep(0.002)
        with self._lock:
            return self._frame_id, self._frame, self._frame_ts

    def frame(self, last_id: int = 0, timeout: float = 2.0) -> tuple[int, bytes | None]:
        """Waits for a frame newer than ``last_id``. Returns (id, bytes)."""
        frame_id, data, _ = self.frame_timed(last_id, timeout)
        return frame_id, data

    @property
    def dropped(self) -> int:
        return self._dropped

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._fd >= 0:
            try:
                fcntl.ioctl(self._fd, VIDIOC_STREAMOFF, struct.pack("=I", BUF_TYPE_VIDEO_CAPTURE))
            except OSError:
                pass
            for m in self._maps:
                m.close()
            self._maps.clear()
            os.close(self._fd)
            self._fd = -1


def list_video_devices() -> list[str]:
    """All /dev/video* nodes from the v4l2 subsystem."""
    base = "/sys/class/video4linux"
    if not os.path.isdir(base):
        return []
    return sorted(f"/dev/{name}" for name in os.listdir(base))


def card_name(path: str) -> str | None:
    """The device card name (VIDIOC_QUERYCAP) or None when it is not a V4L2 node."""
    try:
        fd = open_device(path)
    except OSError:
        return None
    try:
        cap = V4L2Capability()
        fcntl.ioctl(fd, VIDIOC_QUERYCAP, cap)
        return cap.card.split(b"\0")[0].decode(errors="replace")
    except OSError:
        return None
    finally:
        os.close(fd)


def find_device_by_card(card: str) -> str | None:
    """The first device with exactly this card name."""
    return next((p for p in list_video_devices() if card_name(p) == card), None)


def list_input_devices(exclude_card: str) -> list[str]:
    """Devices to choose from as input - without our virtual camera."""
    return [p for p in list_video_devices() if card_name(p) != exclude_card]


class OutputDevice:
    """Writing raw frames to the V4L2 output device (v4l2loopback) through write()."""

    def __init__(self, path: str, size: tuple[int, int], fourcc: bytes = PIX_FMT_YUV420) -> None:
        self.path = path
        self.size = (int(size[0]), int(size[1]))
        self.fourcc = fourcc
        self._fd = -1

    def open(self) -> OutputDevice:
        w, h = self.size
        self._fd = os.open(self.path, os.O_RDWR)
        fmt = V4L2Format()
        fmt.type = BUF_TYPE_VIDEO_OUTPUT
        struct.pack_into("=II4sIII", fmt.raw, PIX_OFF, w, h, self.fourcc, FIELD_NONE, w, w * h * 3 // 2)
        try:
            fcntl.ioctl(self._fd, VIDIOC_S_FMT, fmt)
        except OSError as e:
            self.close()
            raise V4L2Error(f"{self.path}: output S_FMT: {e.strerror}") from e
        aw, ah = struct.unpack_from("=II", fmt.raw, PIX_OFF)
        got = bytes(fmt.raw[PIX_OFF + 8:PIX_OFF + 12])
        if (aw, ah) != (w, h) or got != self.fourcc:
            self.close()
            raise V4L2Error(f"{self.path} did not accept {w}x{h} {self.fourcc.decode()} "
                            f"(got {aw}x{ah} {got!r})")
        return self

    def write(self, data: bytes) -> None:
        os.write(self._fd, data)

    def close(self) -> None:
        if self._fd >= 0:
            os.close(self._fd)
            self._fd = -1
