---
type: Invariant
title: Single PTZ Writer
description: "Only the actuator may write the camera's motion controls, keeping the head model authoritative."
tags: [invariant, camera, safety]
timestamp: 2026-10-02
---

# Single PTZ Writer

A model invariant enforced by construction: the **actuator** is the only component in the engine that
writes the camera's motion controls (absolute pan/tilt/zoom, velocity pan/tilt). Nothing else writes
them, ever.

## Why

Historically other code wrote e.g. `PAN_SPEED=15` directly, leaving motion the head model did not know
about and the camera turning on its own. Funnelling every write through one place removes that entire
class of bugs and guarantees the [head model](/entities/head-dynamics-model.md) is updated with every
command.

## Details the single writer guarantees

- Every command is clamped to the control's range and clamped values are also given to the head model.
- The firmware ignores a write **equal** to the last commanded value, so an equal absolute write is
  preceded by a nudge different by 1″ (imperceptible) and then the right value.
- A velocity axis is never reversed in flight (tilt cannot do it): it is stopped first.
- On startup / reconnect, any leftover motion from another program is zeroed and the position reading
  is accepted as truth.

# Citations
- [eagleeye/actuator.py](/eagleeye/actuator.py)
- [eagleeye/core.py](/eagleeye/core.py)
