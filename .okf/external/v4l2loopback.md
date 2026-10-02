---
type: ExternalSystem
title: v4l2loopback
tags: [context, external, virtual-camera]
timestamp: 2026-10-02
description: The kernel module that provides the /dev/video10 loopback camera the app writes framed video to.
---

# v4l2loopback

The Linux kernel module that creates the virtual camera device the application writes to. It is an
external system, installed by the project's installer but not part of it.

## Why it is needed

V4L2 allows only one program to read a camera stream. When EagleEye tracks, Zoom/Meet/OBS would get no
image. The standard solution is a loopback device: the app reads the physical camera, frames the
person, and writes the result to `/dev/video10`, which conferencing apps pick as a camera.

## Configuration the project relies on

- `card_label="EagleEye"` — receivers select the camera by this name.
- `exclusive_caps=1` — required so Chrome/Meet recognise the device as a camera; must not be set to 0.
- Fixed output format/resolution/FPS, because switching format mid-call breaks the client stream.

See [the virtual camera output contract](/contracts/virtual-camera-output.md) and
[the single-reader constraint](/constraints/v4l2-single-reader.md).

# Citations
- [install.sh](/install.sh)
- [eagleeye/v4l2.py](/eagleeye/v4l2.py)
- [README.md](/README.md)
