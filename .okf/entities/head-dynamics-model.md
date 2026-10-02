---
type: Entity
title: Head Dynamics Model
description: "The model of the real head angle over time, reconstructed from commands and measured firmware dynamics."
resource: /eagleeye/head_model.py
tags: [tracking, camera, model]
timestamp: 2026-10-02
---

# Head Dynamics Model

The software model of **where the camera head actually points at an instant**, reconstructed from the
command history and the measured firmware dynamics. The device cannot report this: read-back returns
the last commanded value, and does not change at all during a velocity move.

## What it represents

Per axis (pan, tilt) and for zoom the model predicts the true angle at time `t` from:

- the last certain resting angle,
- the current motion (absolute S-curve move, or velocity ramp/cruise/coast).

## Identity

The model is authoritative state for the [engine](/contexts/engine.md); the tracking loop, actuator and
director all read angles from it rather than from the device.

## Constants are calibration, not settings

The dynamics defaults (latency, S-curve base/speed/shape, velocity, coasts, zoom, and slower tilt
parameters) are this unit's measured calibration and live **in code**. A `config.json` may only
*override* them for a different camera unit; a missing settings file must never erase the calibration.

# Citations
- [eagleeye/head_model.py](/eagleeye/head_model.py)
- [eagleeye/motion.py](/eagleeye/motion.py)
- [tools/measure_dynamics.py](/tools/measure_dynamics.py)
- [tools/measure_trajectory.py](/tools/measure_trajectory.py)
- [tools/measure_zoom.py](/tools/measure_zoom.py)
