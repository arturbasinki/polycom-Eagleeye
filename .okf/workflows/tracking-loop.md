---
type: Workflow
title: Tracking Loop
description: "The ~15 Hz thread that turns each camera frame into perception, filtering, decisions and PTZ commands."
tags: [tracking, workflow, runtime]
timestamp: 2026-10-02
---

# Tracking Loop

The heartbeat of the system: a thread that runs at the configured rate (~15 Hz) and performs exactly
one pipeline step per iteration.

## Steps per iteration

1. **Fetch** the latest frame with its V4L2 buffer timestamp and take the **shared decoded frame** (the
   virtual camera usually decoded it already); build the detector's half-size BGR from those planes
   ([Decode Once to YUV Planes](/decisions/decode-once-to-yuv-planes.md)).
2. **Perceive**: run RTMO-s, choose the target (the selected person if any, else the largest), and
   build the [head-point observation](/terms/head-point.md) with yaw and head scale.
3. **Identify**: update [person tracks](/entities/tracked-person.md) and the selection state.
4. **Convert & filter**: [TrackingCore](/domains/automatic-tracking.md) maps the observation to a world
   angle, feeds the [Kalman filter](/value-objects/target-estimate.md), and gets an estimate.
5. **Direct**: the [director](/entities/director.md) emits [commands](/value-objects/ptz-command.md).
6. **Act**: the [actuator](/invariants/single-ptz-writer.md) applies them and the head model is
   updated.
7. **Publish** an immutable state snapshot for the UI, and optionally record the step to a session file.

## Safety

- No frames for more than a second freezes the director and zeroes velocities (state: "no image").
- The actuator [watchdog](/invariants/velocity-watchdog.md) stops a velocity axis whose command was not
  refreshed.
- Five consecutive detector errors switch the detector from GPU to CPU.

## Manual control

While tracking is off, the UI can move the camera manually — through the same core (perception off),
so the head model learns about every move and following resumes cleanly.

# Citations
- [eagleeye/tracker.py](/eagleeye/tracker.py)
- [eagleeye/core.py](/eagleeye/core.py)
