---
type: Domain
title: Automatic Tracking
description: "The core subdomain: detect people, keep the chosen person framed, and recover when they are lost."
tags: [domain, core, tracking]
timestamp: 2026-10-02
---

# Automatic Tracking

The core subdomain: keeping the chosen person's head on the framing point while the camera follows
them, and recovering gracefully when they disappear. This is where most of the project's decisions and
measurements live.

## Pipeline

A single loop turns a camera frame into PTZ commands:

1. **Perception** — RTMO-s pose estimation, then the [head point](/terms/head-point.md) and face yaw.
2. **Identity** — [person tracks](/entities/tracked-person.md) across frames, plus the user's
   [selection](/domains/person-identity.md).
3. **World-angle conversion** — pixels → [world angle](/terms/world-angle.md) using the
   [head model](/entities/head-dynamics-model.md) and the measured zoom curve.
4. **Filtering** — a [Kalman target estimate](/value-objects/target-estimate.md) in world angles.
5. **Direction** — the [director](/entities/director.md) decides *where* and *when* to move.
6. **Actuation** — the single [PTZ writer](/invariants/single-ptz-writer.md) moves the head.

## Rules that shape behaviour

- [Framing on the golden-ratio line](/rules/framing-golden-ratio.md), side chosen by face direction.
- [Dwell and hysteresis](/rules/dwell-and-hysteresis.md) before any move.
- [Move only onto a settled target](/rules/settle-before-move.md).
- [Lead only in pan](/rules/lead-only-pan.md).
- [Target loss ladder](/rules/target-loss-ladder.md) and [startup search](/rules/search-scan.md).
- [Auto-zoom shot policy](/rules/zoom-shot-selection.md).

## Starting values

Two [profiles](/value-objects/tracking-profile.md) — *talk* (calm) and *presentation* (keep up) —
parameterise the same engine. The *presentation* profile is explicitly experimental.

# Citations
- [eagleeye/core.py](/eagleeye/core.py)
- [eagleeye/tracker.py](/eagleeye/tracker.py)
- [eagleeye/director.py](/eagleeye/director.py)
- [README.md](/README.md)
