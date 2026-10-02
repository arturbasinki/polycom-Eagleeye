---
type: Entity
title: Director
description: The decision entity that turns a filtered target estimate into camera movement commands.
resource: /eagleeye/director.py
tags: [tracking, decision]
timestamp: 2026-10-02
---

# Director

The movement-decision entity: given a filtered target estimate in world angles, the head model and
the current field of view, it decides **whether, where and how** to move, and emits
[commands](/value-objects/ptz-command.md) for the actuator. It touches no hardware, so the whole
behaviour is testable.

## State

- A **mode**: `tracking`, `searching`, `lost`, `waiting`.
- One small **state machine per axis** (`pan`, `tilt`, `zoom`): `idle → alert → moving` (or
  `following → braking`). Each axis decides independently so an axis already moving is never nudged by
  a half-decided command.
- A framing **side selector**, the last target azimuth, optional `home` pose, the current search plan
  and loss-ladder step.

## Rules it enforces

- [Dwell/hysteresis before moving](/rules/dwell-and-hysteresis.md), with a quiet re-fit band.
- [Move only onto a settled target](/rules/settle-before-move.md), with an escape check.
- [Lead only in pan](/rules/lead-only-pan.md) for the presentation profile.
- [Target loss ladder](/rules/target-loss-ladder.md) and [startup search](/rules/search-scan.md).
- [Auto-zoom shot policy](/rules/zoom-shot-selection.md).

# Citations
- [eagleeye/director.py](/eagleeye/director.py)
- [eagleeye/core.py](/eagleeye/core.py)
