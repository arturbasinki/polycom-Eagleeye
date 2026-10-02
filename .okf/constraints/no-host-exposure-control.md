---
type: Constraint
title: No Host-Controllable Exposure
description: "The camera exposes no exposure/iris control, so backlit faces must be corrected in software."
tags: [constraint, camera, image]
timestamp: 2026-10-02
---

# No Host-Controllable Exposure

A measured hardware constraint: the EagleEye IV exposes **no exposure, iris or gain control** to the
host, and its auto-exposure meters the whole frame. A backlit face saturates or goes dark and cannot be
fixed in the camera.

## Consequences

- Image tuning through V4L2 brightness/contrast/gamma was measured to be insufficient.
- The only remedy is a **software tone curve** on the output — see the
  [light correction rule](/rules/light-correction.md).
- The fix is explicitly a scene-side, **one-shot** operation, not a control loop and not a persisted
  setting.

# Citations
- [docs/superpowers/specs/2026-10-01-subject-light-correction-design.md](/docs/superpowers/specs/2026-10-01-subject-light-correction-design.md)
- [eagleeye/lightfix.py](/eagleeye/lightfix.py)
- [README.md](/README.md)
