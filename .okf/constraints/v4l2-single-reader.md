---
type: Constraint
title: V4L2 Single Stream Reader
description: "A V4L2 stream may be read by only one process, which forces the virtual-camera architecture."
tags: [constraint, camera, v4l2]
timestamp: 2026-10-02
---

# V4L2 Allows a Single Stream Reader

A hard technical constraint: the V4L2 API permits **only one program** to read a camera stream at a
time. When the app tracks, Zoom/Meet/OBS would receive no image; if a browser holds the physical
camera, the app has no picture to track.

## Consequences the solution must respect

- The app must be a **driver**, not an image viewer: read the physical camera, frame the person, and
  expose the result on a [virtual camera](/external/v4l2loopback.md) that receivers select.
- The preview must read from the virtual camera's output, not from the physical device, so it shows
  what participants see.
- Detection overlays are drawn only in the preview; the virtual-camera image stays clean.
- "Device busy" is a normal, recoverable condition: the app retries opening until the browser releases
  the camera.

# Citations
- [README.md](/README.md)
- [eagleeye/engine.py](/eagleeye/engine.py)
