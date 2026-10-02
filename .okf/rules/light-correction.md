---
type: BusinessRule
title: Light Correction
description: "The rule for the one-shot, slope-limited gamma tone curve applied to skin, with reset-wins semantics."
tags: [image, rule, light]
timestamp: 2026-10-02
---

# Light Correction

The business rule for the software tone curve applied to the live image.

## The rule

- Compute the correction **once**, on request, from the skin pixels of the tracked person's face;
  nothing runs per frame except a 256-entry LUT lookup.
- Target a fixed **skin luma**; if the measured median is within a dead zone, treat the face as well lit
  and remove any correction.
- Build a **gamma tone curve** clipped to a minimum and maximum gamma, **slope-limited** (bounds noise
  and banding in deep shadows), and anchor white back at 255 with a ramp that acts on highlights only.
- Pressing "restore defaults" during a measurement **wins**: a generation token makes the older result
  drop its table.
- The correction is **not persisted** and not re-measured automatically; it disappears on reset or quit.

## Where it applies

The LUT is applied to the luma plane of live virtual-camera frames and to the preview when a correction
is active; slates are never corrected. Flawed outcomes (no frame / person / face / skin) are reported as
distinct user messages.

# Citations
- [eagleeye/lightfix.py](/eagleeye/lightfix.py)
- [eagleeye/engine.py](/eagleeye/engine.py)
- [eagleeye/vcam.py](/eagleeye/vcam.py)
