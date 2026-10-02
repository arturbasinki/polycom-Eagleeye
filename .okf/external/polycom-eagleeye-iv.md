---
type: ExternalSystem
title: Polycom EagleEye IV USB Camera
description: The motorised UVC 1.10 camera hardware the project drives; exposes an MJPEG stream and V4L2 PTZ/zoom/focus/image controls.
tags: [context, hardware, external]
timestamp: 2026-10-02
---

# Polycom EagleEye IV USB Camera

The physical camera, used through the generic Linux **V4L2** API as a plain UVC 1.10 device with no
vendor driver. It is an external system: the project configures and commands it, but does not ship it.

## What it provides

- An **MJPEG capture stream** (`/dev/video0`) with V4L2 buffer timestamps.
- **Absolute** pan, tilt, zoom and focus controls, plus **velocity** (`_speed`) pan/tilt controls.
- Image controls: brightness, contrast, saturation, hue, gamma, sharpness, white balance and
  backlight compensation.

## Behaviour the project must live with

The camera's measured quirks are the reason much of the design exists. See the
[constraints](/constraints/camera-does-not-report-position.md) and the
[head/dynamics model](/entities/head-dynamics-model.md): velocity is on/off, absolute moves follow a
firmware S-curve, read-back returns the commanded value, there is no host-controllable exposure, and a
linear zoom model is wrong. Power is 12 V DC centre-NEGATIVE, not USB.

# Citations
- [eagleeye/v4l2.py](/eagleeye/v4l2.py)
- [eagleeye/head_model.py](/eagleeye/head_model.py)
- [README.md](/README.md)
