---
type: Term
title: World Angle
description: The direction the camera would have to point for a given scene point to land at frame centre; unchanged when the camera turns.
tags: [glossary, tracking]
timestamp: 2026-10-02
---

# World Angle

The **world angle** of a scene point is the pan/tilt direction the camera would need for that point to
sit exactly at the centre of the frame. It is expressed in **arcseconds**, the same unit as the
camera's absolute controls (1° = 3600″). Convention measured on the reference unit: positive pan =
right, positive tilt = up; image y grows downwards.

## Why the term matters

Pixels move when the camera turns; world angles do not. Converting every detection into a world angle
(camera angle at frame-exposure time + in-frame offset × scale) is what makes camera motion cancel
out, and is the central idea of the whole system — see
[track in world angles, not pixels](/decisions/track-in-world-angles.md).

# Citations
- [eagleeye/geometry.py](/eagleeye/geometry.py)
- [README.md](/README.md)
