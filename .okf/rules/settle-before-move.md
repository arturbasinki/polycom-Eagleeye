---
type: BusinessRule
title: Move Only Onto a Settled Target
description: "The rule that the camera waits for a moving target to settle before an absolute move, unless it would escape the frame."
tags: [tracking, rule, motion]
timestamp: 2026-10-02
---

# Move Only Onto a Settled Target

Business rule that prevents the camera from arriving "in instalments". An absolute move only hits with
one command a target that is **standing still**; a command issued while a person is standing up or
taking a step aims at an instantaneous position, the person walks on, and the camera must arrive a
second and third time.

## The rule

- Before sending a move, check the target's speed. If it is below a settle threshold (≈2°/s) — move
  now.
- Otherwise wait (up to a couple of seconds) for the target to settle.
- **Escape condition:** even if the target is still moving, move now if the short-horizon prediction
  says it would leave the frame by arrival time. Predict into the future only by a short horizon
  (~0.3 s): humans decelerate at the end of a movement, so extrapolating instantaneous speed over the
  whole travel time over-predicted escapes and caused half-moves.

## Consequences

- In the presentation profile with lead/follow enabled, pan does not wait (a walking target must be
  followed), while tilt still corrects in flight only a settled target.
- In-flight corrections are gated by both a large deviation and ~60 % move progress.

# Citations
- [eagleeye/director.py](/eagleeye/director.py)
