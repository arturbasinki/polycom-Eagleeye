---
type: BusinessRule
title: Auto-Zoom Shot Selection
description: "How auto-zoom picks the shot size and moves only on a lasting, stable change."
tags: [tracking, rule, zoom]
timestamp: 2026-10-02
---

# Auto-Zoom Shot Selection

Business rule for the zoom axis: choose the zoom that makes the person fill the frame according to the
profile's shot.

## The rule

- The shot (CU / MCU / MS) fixes the fraction of the frame height the **eye→shoulder segment** should
  occupy; the zoom that achieves it follows from the measured zoom curve.
- The head scale is measured in **world angles**, so the required zoom does not depend on the current
  zoom.
- Zoom moves only on a **lasting** change: the required factor must differ by more than a band (~20 %,
  in logarithm), persist for a dwell longer than pan/tilt (so leaning in does not zoom), and the target
  must be **stable** within the dwell window (or gestures pump the zoom).
- Arrival is exact; hysteresis resets the dwell only below a lower ratio.
- Auto-zoom is disabled permanently by any [manual zoom](/policies/manual-zoom-disables-autozoom.md).

## Why

Zoom is the most visible axis: a small oscillation is far more distracting than a pan. The band,
dwell and stability gate together prevent pumping.

# Citations
- [eagleeye/director.py](/eagleeye/director.py)
- [eagleeye/framing.py](/eagleeye/framing.py)
- [eagleeye/geometry.py](/eagleeye/geometry.py)
