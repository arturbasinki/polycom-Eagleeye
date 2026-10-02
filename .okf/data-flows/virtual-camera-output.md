---
type: DataFlow
title: Virtual Camera Output
description: "The data flow that turns camera frames or slates into an I420 virtual-camera stream at the camera's size."
tags: [data-flow, virtual-camera, output]
timestamp: 2026-10-02
---

# Virtual Camera Output

How the framed image reaches conferencing apps.

## Sources and sink

- **Source:** the latest MJPEG frame from the physical camera (raw JPEG bytes), or a rendered slate.
- **Sink:** the [v4l2loopback](/external/v4l2loopback.md) device `EagleEye` (`/dev/video10`).

## Flow

1. The output thread runs at a steady 30 fps regardless of camera pauses.
2. It picks the current frame: privacy slate, else the last camera frame, else a "no signal" slate when
   the last frame is stale.
3. The frame is decoded **once, straight to 4:2:0 planes** by the shared decoder
   ([Decode Once to YUV Planes](/decisions/decode-once-to-yuv-planes.md)) and written as I420 without an
   RGB round-trip; the light-correction LUT is applied to a **copy of the Y plane** for the call image,
   never to the shared planes, so the tracker and the next light measurement see the raw frame.
4. The fixed-format frame is written to the loopback device; on a write error or missing device the
   thread retries after a short delay without stopping.

## Output size follows the camera

The output has the **camera stream's size**, i.e. the "Resolution" setting (dimensions made even for
I420) — it is never scaled down to a fixed size. When the stream is reopened at another size, the slates
are re-rendered at that size and the loopback device is reopened with the new format. The 1280×720
constant in code is only the size used before a camera is connected.

## Output format

I420 (YU12), full-range BT.601 luma/chroma, at the camera's size and a steady 30 fps; the slates are
rendered in the active UI language.

## Cost

Measured 2026-10-02 at 1920×1080: ~10 ms of CPU per frame, ~8.5 ms of it the JPEG decode — about a third
of one core at 30 fps. It is now decoded once, straight to planes, with TurboJPEG (~4 ms per frame), and
shared with the tracker: see [Decode Once to YUV Planes](/decisions/decode-once-to-yuv-planes.md).

# Citations
- [eagleeye/vcam.py](/eagleeye/vcam.py)
- [eagleeye/engine.py](/eagleeye/engine.py)
- [README.md](/README.md)
