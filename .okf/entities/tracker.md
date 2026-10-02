---
type: Entity
title: Tracker
description: "The engine entity owning the tracking thread, safety, recording and the state snapshot for views."
tags: [tracking, entity]
timestamp: 2026-10-02
---

# Tracker

The engine entity that owns the tracking thread and the live tracking state. It is a thin layer over
the [pipeline core](/data-flows/frame-to-command.md) and is responsible for the loop's safety and
observability, not for the tracking logic itself.

## Responsibility

- Run the ~15 Hz loop: fetch/decode a frame, perceive, convert/filter, direct, actuate.
- Safety: no frames for > 1 s freezes motion and zeroes velocities; the actuator watchdog guards a hung
  loop; five consecutive detector errors switch GPU → CPU.
- Manual control while tracking is off, through the same core so the
  [head model](/entities/head-dynamics-model.md) knows about every move.
- Session recording (JSONL) and a single immutable state snapshot for the UI.
- Own the [person tracker](/domains/person-identity.md) and the target selection.

## State published to views

Enabled, profile, director mode and per-axis states, note/message, detections, target, frame size,
camera angles, zones/aim/side/shot/yaw/zoom goal, performance (Hz, detection/loop/frame-age ms, moves,
mode) and the people/selection block.

# Citations
- [eagleeye/tracker.py](/eagleeye/tracker.py)
- [eagleeye/core.py](/eagleeye/core.py)
