---
type: Decision
title: Decode MJPEG with Pillow
description: "The decision to decode MJPEG with Pillow to silence libjpeg warnings; superseded for the per-frame path by Decode Once to YUV Planes, kept as the fallback and the one-shot light-measurement decoder."
tags: [decision, performance, encoding]
timestamp: 2026-10-02
---

# Decode MJPEG with Pillow, Not OpenCV

Decision: decode the camera's MJPEG frames with Pillow rather than `cv2.imdecode`.

## Context

The camera appends a few padding bytes before the JPEG EOI marker. OpenCV's libjpeg then prints
`Corrupt JPEG data: N extraneous bytes before marker 0xd9` to **stderr on every frame**, flooding the
terminal with dozens of lines per second. Pillow reports the same issue as a silenceable Python warning.
Re-verified 2026-10-02 with OpenCV 5.0: the message is still printed.

## Decision

- Use Pillow for MJPEG decoding (and for the virtual camera, decoding straight to YCbCr).
- Use `draft` to decode at half scale in the DCT domain for detection, cutting decoding work roughly in
  half.
- Keep the raw MJPEG bytes for the preview, so it is not recompressed while no light correction is
  active (with a correction, the corrected virtual-camera frame is encoded to JPEG once for the preview).

## Consequences

- Measured 2026-10-02 on a 1080p camera frame: Pillow's YCbCr decode 8.5 ms (10.3 ms with the chroma
  rework for I420), the half-scale decode for the tracker 6.0 ms; `cv2.imdecode` to BGR would be 4.9 ms.
  Output is byte-identical to OpenCV's.
- Every frame is decoded twice — full size for the virtual camera (30/s) and half size for the tracker
  (15/s) — together about 40 % of one core at 1080p.
- Pillow is also used to render the localized slates, because OpenCV fonts lack Polish glyphs.

## Status

**Superseded for the per-frame path** by [Decode Once to YUV Planes](/decisions/decode-once-to-yuv-planes.md):
TurboJPEG decodes straight to Y/Cb/Cr planes (~4 ms, no stderr output), once, shared read-only by the
virtual camera and the tracker. This decision still stands for the **Pillow fallback** (a machine without
`libturbojpeg0`) and for the **one-shot light-measurement decoder**.

# Citations
- [eagleeye/detectors.py](/eagleeye/detectors.py)
- [eagleeye/vcam.py](/eagleeye/vcam.py)
- [README.md](/README.md)
