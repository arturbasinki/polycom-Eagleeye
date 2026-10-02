---
type: ValueObject
title: Target Estimate
description: "The filtered target position, velocity and attributes in world angles that the director consumes."
tags: [tracking, filter]
timestamp: 2026-10-02
---

# Target Estimate

The output of the tracking Kalman filter: the target's position and velocity in
[world angles](/terms/world-angle.md) at a given instant, plus smoothed attributes.

## Shape

- `pan`, `tilt` — predicted position in arcseconds at time `t`.
- `v_pan`, `v_tilt` — velocity.
- `last_seen` — the instant of the last accepted measurement; `age = t − last_seen`.
- `yaw` — smoothed face direction (for framing side), may be None.
- `head_scale` — smoothed eye→shoulder segment in world arcseconds (for auto-zoom), may be None.

## Semantics

- Two independent constant-velocity Kalman filters (pan, tilt) with a **gating** step that rejects
  measurements too far from prediction; a run of rejects restarts the filter.
- Measurements from frames while the camera moves carry extra variance (`camera speed × timing error +
  model error`), so they move the estimate less, and a profile may hold the last position during its
  own absolute move.
- Prediction is capped near the last measurement (`max_extrapolation`), except for a walking target,
  which needs prediction through detection gaps.

# Citations
- [eagleeye/target_filter.py](/eagleeye/target_filter.py)
