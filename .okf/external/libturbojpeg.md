---
type: ExternalSystem
title: libturbojpeg
description: "libjpeg-turbo's TurboJPEG API, used to decode MJPEG frames straight to Y/Cb/Cr planes; installed as the libturbojpeg0 package."
tags: [context, external, encoding]
timestamp: 2026-10-02
---

# libturbojpeg

libjpeg-turbo's TurboJPEG API, used to decode the camera's MJPEG frames straight to Y/Cb/Cr 4:2:0
planes. An external system, installed as the Ubuntu package `libturbojpeg0` by the project's installer,
not part of the project.

## Why it is needed

A JPEG already stores Y, Cb and Cr. TurboJPEG hands them out as they are — no RGB conversion and no
chroma upsampling/re-downsampling — which is cheaper (~3.7 ms versus 8.5 ms for a 1080p frame, measured
2026-10-02) and avoids the stderr spam OpenCV's libjpeg produces on this camera's padded frames.

## What the project relies on

- `libturbojpeg.so.0` (TurboJPEG 2.1.x from the Ubuntu archive) through ctypes.
- The 2.x API (`tjInitDecompress`, `tjDecompressHeader3`, `tjDecompressToYUVPlanes`, `tjPlaneWidth`,
  `tjPlaneHeight`, `tjGetErrorCode`, `tjGetErrorStr2`), which 3.x keeps.
- The app must still work without it (Pillow fallback, one log warning).

See [Decode Once to YUV Planes](/decisions/decode-once-to-yuv-planes.md), which also covers the
alternatives rejected (OpenCV, simplejpeg, PyTurboJPEG, nvJPEG).

# Citations
- [eagleeye/jpeg.py](/eagleeye/jpeg.py)
- [install.sh](/install.sh)
