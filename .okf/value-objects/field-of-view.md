---
type: ValueObject
title: Field of View (View)
description: The immutable field-of-view and pixel↔world-angle conversion value used throughout tracking.
tags: [geometry, value-object]
timestamp: 2026-10-02
---

# Field of View (View)

The value object describing how much of the world a frame of a given size covers at a given zoom,
plus the conversions between pixels and [world angles](/terms/world-angle.md).

## Shape

- Frame width and height, the zoom control value, and invert-pan / invert-tilt switches.
- Derived: horizontal field of view (wide FOV / magnification factor), vertical FOV, arcseconds per
  pixel.
- The vertical FOV is derived from the horizontal by the frame aspect ratio.

## Why it is a value object

Zoom changes the field of view, and many rules are expressed as a **fraction of the field of view** so
they scale with zoom. A single immutable object carries the correct FOV for the current (or target)
zoom through every conversion, without recomputing state.

# Citations
- [eagleeye/geometry.py](/eagleeye/geometry.py)
