---
type: Decision
title: "Track in World Angles, Not Pixels"
description: The decision to convert detections to world angles so camera motion cancels out of measurements.
tags: [decision, tracking, architecture]
timestamp: 2026-10-02
---

# Track in World Angles, Not Pixels

The founding decision of the new tracking engine: every detection is converted to a **world angle** —
the camera angle at the moment the frame was exposed, plus the offset inside the frame — before it is
filtered or acted on.

## Context

Pixels move when the camera turns, so a pixel-based tracker reads camera motion as subject motion. The
old loop also ran detect → PID → absolute move → wait, using the device's commanded position as truth
and a PID tuned around a plant that already has its own position controller.

## Decision

- Replace the PID/start-stop loop with a pipeline of small units and **absolute moves**.
- Keep the target in world angles so a camera turn does not change the measurement.
- Split "where the target is" (filter) from "what to do" (director).
- Make the [actuator the only writer](/invariants/single-ptz-writer.md) of motion controls.

## Consequences

- In-flight measurements become usable once the head angle is modelled, so the tracker does not have
  to stop to measure.
- "Last azimuth" and catch-up become simple arithmetic.
- The design is testable without hardware, which is what the closed-loop
  [simulator tests](/tests/test_sim.py) and unit tests rely on.

## Alternatives rejected

Face+body detectors (target jumped 9–13° on posture change) and a velocity-only mechanism (`A2`/`A3`);
variant `A1` (mechanics driven as by an operator, with an extension point for a future digital crop) was
chosen.

# Citations
- [README.md](/README.md)
- [docs/superpowers/specs/2026-09-22-tracking-engine-design.md](/docs/superpowers/specs/2026-09-22-tracking-engine-design.md)
- [eagleeye/geometry.py](/eagleeye/geometry.py)
