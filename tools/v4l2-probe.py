#!/usr/bin/env python3
"""Minimalny odczyt możliwości urządzenia V4L2 przez surowe ioctl (bez v4l-utils)."""
import fcntl
import os
import struct
import sys

V4L2_BUF_TYPE_VIDEO_CAPTURE = 1
V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE = 9

PIXFMT_NAMES = {}
for code, name in [
    (b"YUYV", "YUYV 4:2:2 (bez kompresji)"),
    (b"MJPG", "MJPEG"),
    (b"JPEG", "JPEG"),
    (b"NV12", "NV12"),
    (b"YU12", "YUV420 (planar)"),
    (b"H264", "H.264"),
]:
    PIXFMT_NAMES[code] = name


def fourcc(b):
    return b.decode("ascii", "replace")


def fmt_name(pf):
    return f"{fourcc(pf)} ({PIXFMT_NAMES.get(pf, 'nieznany')})"


def querycap(fd):
    # struct v4l2_capability: 104 bajty
    buf = bytearray(104)
    fcntl.ioctl(fd, 0x80685600, buf)  # VIDIOC_QUERYCAP
    driver, card, bus = (buf[0:16], buf[16:48], buf[48:80])
    version, caps, devcaps = struct.unpack_from("=III", buf, 80)
    return (
        driver.rstrip(b"\0").decode(errors="replace"),
        card.rstrip(b"\0").decode(errors="replace"),
        bus.rstrip(b"\0").decode(errors="replace"),
        version,
        caps,
        devcaps,
    )


def enum_fmt(fd, buf_type):
    out = []
    index = 0
    while True:
        buf = bytearray(64)
        struct.pack_into("=II", buf, 0, index, buf_type)  # index, type
        try:
            fcntl.ioctl(fd, 0xC0405602, buf)  # VIDIOC_ENUM_FMT
        except OSError:
            break
        _idx, _type, flags = struct.unpack_from("=III", buf, 0)
        desc = buf[12:44].rstrip(b"\0").decode(errors="replace")
        pixelformat = bytes(buf[44:48])
        out.append((index, desc, pixelformat, flags))
        index += 1
    return out


def enum_framesizes(fd, pixelformat):
    out = []
    index = 0
    while True:
        buf = bytearray(44)
        struct.pack_into("=I", buf, 0, index)
        buf[4:8] = pixelformat
        try:
            fcntl.ioctl(fd, 0xC02C564A, buf)  # VIDIOC_ENUM_FRAMESIZES
        except OSError:
            break
        ftype = struct.unpack_from("=I", buf, 8)[0]
        if ftype == 1:  # discrete
            w, h = struct.unpack_from("=II", buf, 12)
            out.append((w, h))
        elif ftype == 2:  # stepwise
            mw, Maw, sw, mh, Mah, sh = struct.unpack_from("=IIIIII", buf, 12)
            out.append((f"{mw}-{Maw}/{sw}", f"{mh}-{Mah}/{sh}"))
        index += 1
    return out


def enum_intervals(fd, pixelformat, width, height):
    out = []
    index = 0
    while True:
        buf = bytearray(52)
        struct.pack_into("=I", buf, 0, index)
        buf[4:8] = pixelformat
        struct.pack_into("=II", buf, 8, width, height)
        try:
            fcntl.ioctl(fd, 0xC034564B, buf)  # VIDIOC_ENUM_FRAMEINTERVALS
        except OSError:
            break
        itype = struct.unpack_from("=I", buf, 16)[0]
        if itype == 1:
            num, den = struct.unpack_from("=II", buf, 20)
            out.append(den / num if num else 0.0)
        index += 1
    return out


for dev in sys.argv[1:]:
    print("=" * 70)
    print(dev)
    print("=" * 70)
    try:
        fd = os.open(dev, os.O_RDWR | os.O_NONBLOCK)
    except OSError as e:
        print(f"  nie można otworzyć: {e}")
        continue
    try:
        driver, card, bus, version, caps, devcaps = querycap(fd)
        print(f"  driver={driver}  card={card}")
        print(f"  bus={bus}  version={version}")
        print(f"  capabilities=0x{caps:08x}  device_caps=0x{devcaps:08x}")
        if not (devcaps & 0x00000001):
            print("  >> to NIE jest węzeł przechwytujący wideo (brak VIDEO_CAPTURE)")

        for buf_type, tname in [
            (V4L2_BUF_TYPE_VIDEO_CAPTURE, "VIDEO_CAPTURE"),
            (V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE, "VIDEO_CAPTURE_MPLANE"),
        ]:
            fmts = enum_fmt(fd, buf_type)
            if not fmts:
                continue
            print(f"\n  --- formaty ({tname}) ---")
            for _idx, desc, pf, flags in fmts:
                print(f"    {fmt_name(pf):50s} desc={desc!r}")
                sizes = enum_framesizes(fd, pf)
                for wh in sizes:
                    if isinstance(wh[0], int):
                        fps = enum_intervals(fd, pf, wh[0], wh[1])
                        fps_s = ", ".join(f"{f:.0f}" for f in sorted(set(fps), reverse=True)) or "?"
                        print(f"        {wh[0]}x{wh[1]}  @ {fps_s} fps")
                    else:
                        print(f"        {wh}")
    finally:
        os.close(fd)
