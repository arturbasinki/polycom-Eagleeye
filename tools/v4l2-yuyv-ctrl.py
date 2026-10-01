#!/usr/bin/env python3
"""Testing the second format (YUYV) and dumping the V4L2 controls of the EagleEye IV camera.

Usage:
  v4l2-yuyv-ctrl.py grab  /dev/video0 output.png [width] [height]
  v4l2-yuyv-ctrl.py ctrls /dev/video0
"""
import ctypes
import fcntl
import mmap
import os
import select
import struct
import sys
import time

BUF_TYPE_CAPTURE = 1
MEMORY_MMAP = 1
FIELD_NONE = 1
PIX_OFF = 4  # struct v4l2_pix_format sits at offset 8 of the structure, i.e. 4 in "raw"

CTRL_FLAG_NEXT_CTRL = 0x80000000


def _IOC(d, t, n, s):
    return (d << 30) | (s << 16) | (ord(t) << 8) | n


def _IOWR(t, n, s):
    return _IOC(3, t, n, s)


def _IOW(t, n, s):
    return _IOC(1, t, n, s)


class V4L2Format(ctypes.Structure):
    _fields_ = [("type", ctypes.c_uint32), ("raw", ctypes.c_uint8 * 204)]


class V4L2Requestbuffers(ctypes.Structure):
    _fields_ = [
        ("count", ctypes.c_uint32),
        ("type", ctypes.c_uint32),
        ("memory", ctypes.c_uint32),
        ("capabilities", ctypes.c_uint32),
        ("reserved", ctypes.c_uint32 * 1),
    ]


class Timeval(ctypes.Structure):
    _fields_ = [("tv_sec", ctypes.c_long), ("tv_usec", ctypes.c_long)]


class Timecode(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_uint8),
        ("flags", ctypes.c_uint8),
        ("frames", ctypes.c_uint8),
        ("seconds", ctypes.c_uint8),
        ("minutes", ctypes.c_uint8),
        ("hours", ctypes.c_uint8),
        ("userbits", ctypes.c_uint8 * 4),
    ]


class _OffUnion(ctypes.Union):
    _fields_ = [
        ("offset", ctypes.c_uint32),
        ("userptr", ctypes.c_ulong),
        ("planes", ctypes.c_void_p),
        ("fd", ctypes.c_int32),
    ]


class _LastUnion(ctypes.Union):
    _fields_ = [("request_fd", ctypes.c_int32), ("reserved", ctypes.c_uint32)]


class V4L2Buffer(ctypes.Structure):
    _fields_ = [
        ("index", ctypes.c_uint32),
        ("type", ctypes.c_uint32),
        ("bytesused", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("field", ctypes.c_uint32),
        ("timestamp", Timeval),
        ("timecode", Timecode),
        ("sequence", ctypes.c_uint32),
        ("memory", ctypes.c_uint32),
        ("m", _OffUnion),
        ("length", ctypes.c_uint32),
        ("reserved2", ctypes.c_uint32),
        ("last", _LastUnion),
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


S_FMT = _IOWR("V", 5, 208)
REQBUFS = _IOWR("V", 8, 20)
QUERYBUF = _IOWR("V", 9, 88)
QBUF = _IOWR("V", 15, 88)
DQBUF = _IOWR("V", 17, 88)
STREAMON = _IOW("V", 18, 4)
STREAMOFF = _IOW("V", 19, 4)
QUERYCTRL = _IOWR("V", 36, ctypes.sizeof(V4L2QueryCtrl))


def grab(dev, out_png, width, height, pixfmt=b"YUYV"):
    fd = os.open(dev, os.O_RDWR | os.O_NONBLOCK)
    maps = []
    try:
        fmt = V4L2Format()
        fmt.type = BUF_TYPE_CAPTURE
        struct.pack_into("=II", fmt.raw, PIX_OFF, width, height)
        fmt.raw[PIX_OFF + 8 : PIX_OFF + 12] = pixfmt
        struct.pack_into("=I", fmt.raw, PIX_OFF + 12, FIELD_NONE)
        fcntl.ioctl(fd, S_FMT, fmt)
        w, h = struct.unpack_from("=II", fmt.raw, PIX_OFF)
        pf = bytes(fmt.raw[PIX_OFF + 8 : PIX_OFF + 12]).decode("ascii", "replace")
        print(f"[S_FMT] {w}x{h} {pf}")

        req = V4L2Requestbuffers()
        req.count = 3
        req.type = BUF_TYPE_CAPTURE
        req.memory = MEMORY_MMAP
        fcntl.ioctl(fd, REQBUFS, req)
        print(f"[REQBUFS] {req.count} buffers")

        for i in range(req.count):
            b = V4L2Buffer()
            b.type = BUF_TYPE_CAPTURE
            b.memory = MEMORY_MMAP
            b.index = i
            fcntl.ioctl(fd, QUERYBUF, b)
            maps.append(mmap.mmap(fd, b.length, prot=mmap.PROT_READ | mmap.PROT_WRITE,
                                  flags=mmap.MAP_SHARED, offset=b.m.offset))
            fcntl.ioctl(fd, QBUF, b)

        fcntl.ioctl(fd, STREAMON, struct.pack("=I", BUF_TYPE_CAPTURE))
        print("[STREAMON] waiting for a complete YUYV frame...")
        expected = w * h * 2
        got = None
        deadline = time.time() + 20.0
        while time.time() < deadline:
            r, _, _ = select.select([fd], [], [], 5.0)
            if not r:
                continue
            b = V4L2Buffer()
            b.type = BUF_TYPE_CAPTURE
            b.memory = MEMORY_MMAP
            fcntl.ioctl(fd, DQBUF, b)
            data = maps[b.index][: b.bytesused]
            if b.bytesused >= expected:
                got = (b.bytesused, data[:expected])
                print(f"  [OK] buf={b.index} {b.bytesused} B >= {expected} B (complete frame)")
            fcntl.ioctl(fd, QBUF, b)
            if got:
                break

        fcntl.ioctl(fd, STREAMOFF, struct.pack("=I", BUF_TYPE_CAPTURE))
        if not got:
            print("  failed to receive a complete YUYV frame")
            return 1

        import struct as _s
        cl = lambda v: 0 if v < 0 else (255 if v > 255 else v)
        cr_r = [int(1.402 * (v - 128)) for v in range(256)]
        cr_g = [int(-0.714 * (v - 128)) for v in range(256)]
        cb_g = [int(-0.344 * (u - 128)) for u in range(256)]
        cb_b = [int(1.772 * (u - 128)) for u in range(256)]
        raw = got[1]
        rgb = bytearray(w * h * 3)
        o = 0
        for i in range(0, len(raw), 4):
            y0, u, y1, v = raw[i], raw[i + 1], raw[i + 2], raw[i + 3]
            r1, g1, b1 = cr_r[v], cr_g[v] + cb_g[u], cb_b[u]
            rgb[o] = cl(y0 + r1); rgb[o + 1] = cl(y0 + g1); rgb[o + 2] = cl(y0 + b1)
            rgb[o + 3] = cl(y1 + r1); rgb[o + 4] = cl(y1 + g1); rgb[o + 5] = cl(y1 + b1)
            o += 6
        from PIL import Image
        im = Image.frombytes("RGB", (w, h), bytes(rgb))
        im.save(out_png)
        print(f"[YUYV->RGB conversion] saved {out_png} ({w}x{h})")
        return 0
    finally:
        for m in maps:
            m.close()
        os.close(fd)


def ctrls(dev):
    fd = os.open(dev, os.O_RDWR | os.O_NONBLOCK)
    try:
        print(f"V4L2 controls for {dev}:")
        qc = V4L2QueryCtrl()
        qc.id = CTRL_FLAG_NEXT_CTRL
        rows = []
        while True:
            try:
                fcntl.ioctl(fd, QUERYCTRL, qc)
            except OSError:
                break
            name = qc.name.split(b"\0")[0].decode(errors="replace")
            rows.append((qc.id, name, qc.minimum, qc.maximum, qc.step, qc.default_value, qc.flags))
            qc.id = qc.id | CTRL_FLAG_NEXT_CTRL
        if not rows:
            print("  no controls at all")
            return 0
        for cid, name, mn, mx, st, dv, fl in rows:
            print(f"  0x{cid:08x}  {name:28s} min={mn:<8} max={mx:<8} step={st:<5} def={dv:<6} flags=0x{fl:x}")
        print(f"\nTotal: {len(rows)} controls")
        ptz = [r for r in rows if 0x009A0000 <= r[0] <= 0x009AFFFF]
        print(f"CAMERA class controls (PTZ etc.): {len(ptz)}")
        return 0
    finally:
        os.close(fd)


class V4L2ExtControl(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [
            ("value", ctypes.c_int32),
            ("value64", ctypes.c_int64),
            ("string", ctypes.c_char_p),
            ("ptr", ctypes.c_void_p),
        ]

    _fields_ = [
        ("id", ctypes.c_uint32),
        ("size", ctypes.c_uint32),
        ("u", _U),
        ("reserved2", ctypes.c_uint32 * 1),
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


# V4L2_CTRL_WHICH_CUR_VAL == 0 -> we operate on the current control value,
# not on the default value or a requested request.
G_EXT_CTRLS = _IOWR("V", 71, ctypes.sizeof(V4L2ExtControls))
S_EXT_CTRLS = _IOWR("V", 72, ctypes.sizeof(V4L2ExtControls))


def _ext_ctrls(dev, ctrl_id, value=None):
    """Reading (value=None) or writing a control through EXT_CTRLS."""
    fd = os.open(dev, os.O_RDWR | os.O_NONBLOCK)
    try:
        ctl = V4L2ExtControl()
        ctl.id = ctrl_id
        ctl.size = 0
        if value is not None:
            ctl.u.value = value
        ctrls = V4L2ExtControls()
        ctrls.which = 0  # V4L2_CTRL_WHICH_CUR_VAL
        ctrls.count = 1
        ctrls.error_idx = 0
        ctrls.controls = ctypes.pointer(ctl)
        fcntl.ioctl(fd, G_EXT_CTRLS if value is None else S_EXT_CTRLS, ctrls)
        return ctl.u.value
    finally:
        os.close(fd)


def set_ctrl(dev, ctrl_id, value):
    try:
        got = _ext_ctrls(dev, ctrl_id, value)
        print(f"  set 0x{ctrl_id:08x} = {got}")
        return 0
    except OSError as e:
        print(f"  error: {e}")
        return 1


def get_ctrl(dev, ctrl_id):
    return _ext_ctrls(dev, ctrl_id, None)


if __name__ == "__main__":
    mode = sys.argv[1]
    dev = sys.argv[2] if len(sys.argv) > 2 else "/dev/video0"
    if mode == "grab":
        out = sys.argv[3] if len(sys.argv) > 3 else "/tmp/yuyv.png"
        w = int(sys.argv[4]) if len(sys.argv) > 4 else 1280
        h = int(sys.argv[5]) if len(sys.argv) > 5 else 720
        sys.exit(grab(dev, out, w, h))
    elif mode == "ctrls":
        sys.exit(ctrls(dev))
    elif mode == "set":
        sys.exit(set_ctrl(dev, int(sys.argv[3], 0), int(sys.argv[4], 0)))
    elif mode == "get":
        print(f"0x{int(sys.argv[3], 0):08x} = {get_ctrl(dev, int(sys.argv[3], 0))}")
        sys.exit(0)
    else:
        print(__doc__)
        sys.exit(2)
