---
type: ValueObject
title: PTZ Command
description: "An immutable camera-movement instruction (absolute, velocity or zoom) passed from decision to actuator."
tags: [tracking, command]
timestamp: 2026-10-02
---

# PTZ Command

An immutable instruction emitted by the [director](/entities/director.md) and applied by the actuator.
It is the language between decision and hardware, and a unit of the system's behaviour.

## Shape

- `kind`: `abs` (absolute move to a value), `vel` (constant-speed direction −1/0/+1), or `zoom`
  (absolute zoom control value).
- `axis`: `pan` | `tilt` | `zoom`.
- `value`: for `abs` an angle in arcseconds; for `vel` a direction; for `zoom` a control value.

## Semantics

- Absolute moves are the default way to position the head; they let the firmware generate its S-curve
  and are re-anchored by the [head model](/entities/head-dynamics-model.md).
- Velocity commands are refreshed each tick while valid and stopped explicitly; tilt never uses
  velocity in the director's rules.
- The actuator clamps a command to the control's range and nudges equal absolute values — see the
  [single-writer invariant](/invariants/single-ptz-writer.md).

# Citations
- [eagleeye/director.py](/eagleeye/director.py)
- [eagleeye/actuator.py](/eagleeye/actuator.py)
