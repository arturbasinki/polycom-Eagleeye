---
type: Domain
title: PTZ Camera Control
description: "Driving the motorised head, optics and image controls of the camera, and saving/recalling full camera poses."
tags: [domain, camera]
timestamp: 2026-10-02
---

# PTZ Camera Control

The generic (supporting) subdomain of operating the physical camera: moving the head, changing zoom
and focus, tuning the image, and storing complete poses.

## Model

- The camera exposes [V4L2 controls](/contracts/camera-controls.md): absolute pan/tilt/zoom/focus,
  velocity pan/tilt, and image controls.
- A **position** is an angle of the head; a **preset** is a complete pose
  ([camera preset](/value-objects/camera-preset.md)).
- All motion writes go through one [actuator](/invariants/single-ptz-writer.md) so no other code touches
  the head.

## Rules

- Absolute moves are the norm; velocity moves exist mainly for constant-speed following.
- The firmware ignores a write equal to the last commanded value, so equal absolute writes are
  nudged first — see the [single-writer invariant](/invariants/single-ptz-writer.md).
- A velocity write is valid only briefly and is refreshed by the loop or stopped by a watchdog —
  see the [velocity watchdog invariant](/invariants/velocity-watchdog.md).

## Why it is separate

Tracking needs to know *where the camera truly points*, which the device cannot tell it. That
concern lives in the [automatic tracking domain](/domains/automatic-tracking.md) and the
[head dynamics model](/entities/head-dynamics-model.md).

# Citations
- [eagleeye/v4l2.py](/eagleeye/v4l2.py)
- [eagleeye/actuator.py](/eagleeye/actuator.py)
- [eagleeye/config.py](/eagleeye/config.py)
