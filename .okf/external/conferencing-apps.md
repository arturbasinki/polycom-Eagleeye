---
type: ExternalSystem
title: Conferencing and Recording Apps
description: "The external applications (Meet, Teams, Zoom, OBS) that receive the virtual camera image."
tags: [context, external, consumers]
timestamp: 2026-10-02
---

# Conferencing and Recording Apps

The downstream consumers of the virtual camera: Google Meet and Teams (in Chrome), Zoom, and OBS
Studio. They are external systems; the project's job is to present a camera-like device they accept.

## What they require of the output

- A camera device that is **being written to** at the moment the app builds its camera list. Chrome
  enumerates loopback cameras at startup; if nothing writes, `EagleEye` is absent until a restart of
  the browser.
- A **fixed format, resolution and FPS** — switching format mid-call breaks the receiver's stream.
- The device declared with `exclusive_caps=1` so it is recognised as a camera, not a capture device.

## Consequence for the product

The app must run as a background writer and never let a browser hold the physical camera; selecting the
physical device in Meet makes the app lose its own stream. See
[the output contract](/contracts/virtual-camera-output.md).

# Citations
- [README.md](/README.md)
- [eagleeye/vcam.py](/eagleeye/vcam.py)
