---
type: Constraint
title: No Host-Controllable Exposure
description: "The camera exposes no exposure/iris control and is weak in low light, so backlit faces are corrected in software and dark scenes need light."
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

## Low light and dynamic range

The sensor is weak in low light and has a narrow dynamic range: in a dim room the camera's own
auto-exposure raises gain, the picture gets visibly noisy, and conferencing apps' encoders (Meet) make
that noise look like lost resolution. Checked 2026-10-02 after a "the image looks worse in Meet" report:
the virtual camera output was byte-identical in luma to the previous pipeline (chroma within 1 level for
99 % of pixels), 1920×1080 at 30.1 fps with no repeated frames — the degradation was the camera in the
dark plus Meet's compression, not the application. Software cannot recover detail the sensor did not
capture; the remedy is scene lighting.

# Citations
- [docs/superpowers/specs/2026-10-01-subject-light-correction-design.md](/docs/superpowers/specs/2026-10-01-subject-light-correction-design.md)
- [eagleeye/lightfix.py](/eagleeye/lightfix.py)
- [README.md](/README.md)
