---
type: ValueObject
title: Observation
description: "The per-frame head measurement in pixels plus capture time, yaw and head scale."
tags: [perception, value-object, tracking]
timestamp: 2026-10-02
---

# Observation

The perception value object handed to the tracking core for one frame: the
[head point](/terms/head-point.md) in **frame pixels** together with the attributes derived from the
same pose.

## Shape

- `x`, `y` — head point in frame pixels.
- `t` — frame capture time (`CLOCK_MONOTONIC`), from the V4L2 buffer timestamp.
- `score`, `source` (e.g. `"pose"`), `box`.
- `yaw` — face direction in [−1, 1] (nose relative to the visible eyes/ears), may be None.
- `head_scale_px` — eye→shoulder segment in pixels, may be None.

## Role

The observation is still in pixels: the tracking core converts it to a
[world angle](/terms/world-angle.md) using the camera angle at `t` from the
[head model](/entities/head-dynamics-model.md). Keeping the raw pixel point plus the frame time is what
makes the conversion correct even while the camera moves.

# Citations
- [eagleeye/perception.py](/eagleeye/perception.py)
- [eagleeye/core.py](/eagleeye/core.py)
