#!/usr/bin/env python3
"""Grabbing one frame from a V4L2 camera through mmap (without v4l-utils/ffmpeg).

Usage: v4l2-grab.py /dev/video0 output.jpg [width height]
"""
import ctypes
import fcntl
import mmap
import os
import select
import struct
import sys
import time

V4L2_BUF_TYPE_VIDEO_CAPTURE = 1
V4L2_MEMORY_MMAP = 1
V4L2_FIELD_NONE = 1

# struct v4l2_format: type(0) + padding(4) + union fmt at offset 8.
# The union contains a pointer, so it is aligned to 8 bytes - hence these 4 bytes
# of padding. struct v4l2_pix_format therefore sits at offset 8 of the structure,
# i.e. offset 4 in our "raw" buffer.
PIX_OFF = 4


def _IOC(direction, typ, nr, size):
    return (direction << 30) | (size << 16) | (ord(typ) << 8) | nr


def _IOWR(typ, nr, size):
    return _IOC(3, typ, nr, size)


def _IOW(typ, nr, size):
    return _IOC(1, typ, nr, size)


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


class _OffsetUnion(ctypes.Union):
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
        ("m", _OffsetUnion),
        ("length", ctypes.c_uint32),
        ("reserved2", ctypes.c_uint32),
        ("last", _LastUnion),
    ]


VIDIOC_S_FMT = _IOWR("V", 5, ctypes.sizeof(V4L2Format))
VIDIOC_REQBUFS = _IOWR("V", 8, ctypes.sizeof(V4L2Requestbuffers))
VIDIOC_QUERYBUF = _IOWR("V", 9, ctypes.sizeof(V4L2Buffer))
VIDIOC_QBUF = _IOWR("V", 15, ctypes.sizeof(V4L2Buffer))
VIDIOC_DQBUF = _IOWR("V", 17, ctypes.sizeof(V4L2Buffer))
VIDIOC_STREAMON = _IOW("V", 18, 4)
VIDIOC_STREAMOFF = _IOW("V", 19, 4)


def main():
    dev = sys.argv[1] if len(sys.argv) > 1 else "/dev/video0"
    out = sys.argv[2] if len(sys.argv) > 2 else "/tmp/eagleeye-frame.jpg"
    width = int(sys.argv[3]) if len(sys.argv) > 3 else 1920
    height = int(sys.argv[4]) if len(sys.argv) > 4 else 1080

    if ctypes.sizeof(V4L2Format) != 208 or ctypes.sizeof(V4L2Buffer) != 88:
        print(
            f"WARNING: structure sizes {ctypes.sizeof(V4L2Format)}/"
            f"{ctypes.sizeof(V4L2Buffer)} (expected 208/88)"
        )

    fd = os.open(dev, os.O_RDWR | os.O_NONBLOCK)
    maps = []
    try:
        # 1. Set the MJPEG format at the requested resolution
        fmt = V4L2Format()
        fmt.type = V4L2_BUF_TYPE_VIDEO_CAPTURE
        struct.pack_into("=II", fmt.raw, PIX_OFF, width, height)
        fmt.raw[PIX_OFF + 8 : PIX_OFF + 12] = b"MJPG"
        struct.pack_into("=I", fmt.raw, PIX_OFF + 12, V4L2_FIELD_NONE)
        fcntl.ioctl(fd, VIDIOC_S_FMT, fmt)
        w, h = struct.unpack_from("=II", fmt.raw, PIX_OFF)
        pf = bytes(fmt.raw[PIX_OFF + 8 : PIX_OFF + 12]).decode("ascii", "replace")
        bpl, sizeimage = struct.unpack_from("=II", fmt.raw, PIX_OFF + 16)
        print(f"[S_FMT] {w}x{h} {pf} bytesperline={bpl} sizeimage={sizeimage}")

        # 2. Reserve buffers
        req = V4L2Requestbuffers()
        req.count = 4
        req.type = V4L2_BUF_TYPE_VIDEO_CAPTURE
        req.memory = V4L2_MEMORY_MMAP
        fcntl.ioctl(fd, VIDIOC_REQBUFS, req)
        print(f"[REQBUFS] got {req.count} buffers")
        if req.count < 2:
            raise RuntimeError("too few buffers")

        # 3. Map and queue
        for i in range(req.count):
            buf = V4L2Buffer()
            buf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE
            buf.memory = V4L2_MEMORY_MMAP
            buf.index = i
            fcntl.ioctl(fd, VIDIOC_QUERYBUF, buf)
            m = mmap.mmap(
                fd, buf.length, prot=mmap.PROT_READ | mmap.PROT_WRITE, flags=mmap.MAP_SHARED,
                offset=buf.m.offset,
            )
            maps.append(m)
            fcntl.ioctl(fd, VIDIOC_QBUF, buf)

        # 4. Start the stream
        fcntl.ioctl(fd, VIDIOC_STREAMON, struct.pack("=I", V4L2_BUF_TYPE_VIDEO_CAPTURE))
        print("[STREAMON] stream started, waiting for a frame...")

        # 5. Collect frames. The first frames after STREAMON are sometimes truncated
        # (the MJPEG encoder is still stabilizing), so we accept only
        # complete JPEGs: SOI at the start and EOI at the end.
        saved = 0
        skipped = 0
        deadline = time.time() + 20.0
        while saved < 3 and time.time() < deadline:
            r, _, _ = select.select([fd], [], [], 5.0)
            if not r:
                print("  timeout - no frame")
                continue
            buf = V4L2Buffer()
            buf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE
            buf.memory = V4L2_MEMORY_MMAP
            fcntl.ioctl(fd, VIDIOC_DQBUF, buf)
            data = maps[buf.index][: buf.bytesused]
            complete = data[:2] == b"\xff\xd8" and data[-2:] == b"\xff\xd9"
            if complete:
                with open(out, "wb") as f:
                    f.write(data)
                print(
                    f"  [OK] buf={buf.index} seq={buf.sequence} "
                    f"{buf.bytesused} B flags=0x{buf.flags:02x} -> {out}"
                )
                saved += 1
            else:
                skipped += 1
                if skipped <= 5:
                    print(
                        f"  [rejected] buf={buf.index} seq={buf.sequence} "
                        f"{buf.bytesused} B flags=0x{buf.flags:02x} "
                        f"SOI={data[:2] == b'\\xff\\xd8'} EOI={data[-2:] == b'\\xff\\xd9'}"
                    )
            fcntl.ioctl(fd, VIDIOC_QBUF, buf)

        fcntl.ioctl(fd, VIDIOC_STREAMOFF, struct.pack("=I", V4L2_BUF_TYPE_VIDEO_CAPTURE))
        print(f"[STREAMOFF] saved complete frames: {saved}, rejected: {skipped}")
        return 0 if saved else 1
    finally:
        for m in maps:
            m.close()
        os.close(fd)


if __name__ == "__main__":
    sys.exit(main())
