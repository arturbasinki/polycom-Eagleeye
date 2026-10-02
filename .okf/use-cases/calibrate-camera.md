---
type: UseCase
title: Calibrate the Camera
description: The use case of measuring one camera unit and recording the result as a configuration override.
tags: [camera, use-case, calibration]
timestamp: 2026-10-02
---

# Calibrate the Camera

## Goal

Measure a specific EagleEye IV unit so tracking is accurate on that unit, and record the result as a
**configuration override** — not as calibration in code.

## Main flow

1. Run the measurement tools against the physical camera:
   - `measure_dynamics.py` — pan/tilt/zoom move dynamics,
   - `measure_zoom.py` — the zoom magnification curve,
   - `measure_trajectory.py` — the absolute-move trajectory (and the slower tilt).
2. `--save` writes the measured values into `config.json["dynamics"]` as an override.
3. The [head model](/entities/head-dynamics-model.md) reads overrides over the in-code defaults;
   unknown or junk values are ignored so the code calibration cannot be erased.

## Notes

- The default calibration is this unit's measured values and lives in code (see
  [the invariant](/invariants/dynamics-calibration-in-code.md)).
- Pan/tilt sign convention was measured on one unit; if another differs, the UI has invert-pan /
  invert-tilt switches.
- Contributing measurements from other units is the most useful way to validate the calibration.

# Citations
- [tools/measure_dynamics.py](/tools/measure_dynamics.py)
- [tools/measure_zoom.py](/tools/measure_zoom.py)
- [tools/measure_trajectory.py](/tools/measure_trajectory.py)
- [eagleeye/head_model.py](/eagleeye/head_model.py)
