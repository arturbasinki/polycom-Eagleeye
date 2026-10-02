---
type: QualityAttribute
title: "Smooth, Calm Tracking"
description: "The non-functional requirement that the camera moves rarely and smoothly, like a calm operator."
tags: [quality, tracking, nfr]
timestamp: 2026-10-02
---

# Smooth, Calm Tracking

The primary quality attribute of the product: the camera should feel like a calm human operator —
rare, smooth, decisive moves — not like a machine chasing a point. Classified under ISO/IEC 25010 as
usability/behavioural quality of the interaction.

## How it is achieved

- [Dwell and hysteresis](/rules/dwell-and-hysteresis.md) plus a composition band and quiet re-fit.
- [Move only onto a settled target](/rules/settle-before-move.md) to avoid arriving in instalments.
- One command per move, with in-flight correction gated on deviation and 60 % progress.
- A fast-tracking [Kalman filter](/value-objects/target-estimate.md) whose truthfulness is separated
  from the decision of whether to react.
- Absolute moves riding the firmware S-curve rather than a hand-tuned PID.

## How it is verified

- Closed-loop **simulation** with scenario metrics (sitting, walking, searching, escaping), where
  smoothness thresholds in assertions may not be changed without the user's agreement.
- Live-camera integration tests that must pass at a working zoom, not only at 0.
- Session recording (JSONL) for post-hoc diagnosis and offline replay with different settings.

# Citations
- [tests/test_sim.py](/tests/test_sim.py)
- [eagleeye/sim.py](/eagleeye/sim.py)
- [README.md](/README.md)
