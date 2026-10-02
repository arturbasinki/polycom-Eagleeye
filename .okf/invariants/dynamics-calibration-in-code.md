---
type: Invariant
title: Head Calibration Lives in Code
description: Measured camera calibration must live in code; config.json may only override it.
tags: [invariant, camera, configuration]
timestamp: 2026-10-02
---

# Head Calibration Lives in Code

An invariant about where the camera's measured dynamics may live: the defaults in the
[head model](/entities/head-dynamics-model.md) are this unit's **calibration and must stay in code**.
`config.json` may only **override** them (for a different camera unit), never be their sole home.

## Why

A settings file is optional, machine-local and can be deleted; the camera must track well without it. If
calibration lived only in the file, losing the file would silently mis-model the head and degrade
tracking. Measurement tools therefore write an *override* (`--save`), not the calibration itself.

## Corollary: measurement-derived constants are not configuration

The same principle applies to other measured constants (Kalman noise parameters, zoom curve, tone-curve
limits): they are calibration values fixed in code with provenance in comments, not user knobs. Only a
small whitelisted subset of parameters is exposed as overrides.

# Citations
- [eagleeye/head_model.py](/eagleeye/head_model.py)
- [eagleeye/target_filter.py](/eagleeye/target_filter.py)
- [tools/measure_dynamics.py](/tools/measure_dynamics.py)
