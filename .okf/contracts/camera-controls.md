---
type: Contract
title: Camera Controls Contract
description: The V4L2 control IDs and rules through which the engine commands the physical camera.
tags: [contract, camera, v4l2]
timestamp: 2026-10-02
---

# Camera Controls Contract

The port through which the engine commands the physical camera: the V4L2 control IDs it uses, and the
separation of stream and control descriptors.

## Controls used

- **Motion:** `PAN_ABSOLUTE`, `TILT_ABSOLUTE`, `PAN_SPEED`, `TILT_SPEED`, `ZOOM_ABSOLUTE`,
  `ZOOM_CONTINUOUS` (zeroed at startup).
- **Optics:** `FOCUS_ABSOLUTE`, `FOCUS_AUTO`.
- **Image:** `BRIGHTNESS`, `CONTRAST`, `SATURATION`, `HUE`, `GAMMA`, `SHARPNESS`,
  `WHITE_BALANCE_AUTO`, `WHITE_BALANCE_TEMP`, `BACKLIGHT_COMP`, `POWER_LINE_FREQ`.

## Rules

- Each control has a range read from the device; writes are clamped to it (and the clamp is mirrored in
  the [head model](/entities/head-dynamics-model.md)).
- The stream and the controls use **separate file descriptors**, so a control write never disturbs
  capture and vice versa.
- Motion writes go only through the [actuator](/invariants/single-ptz-writer.md).
- Camera control values do **not** persist in the device; only presets in `config.json` do.

# Citations
- [eagleeye/v4l2.py](/eagleeye/v4l2.py)
- [eagleeye/actuator.py](/eagleeye/actuator.py)
