---
type: Term
title: Framing Point
description: "The frame location the head is placed on: the upper golden-ratio line, centred or to a side."
tags: [glossary, framing]
timestamp: 2026-10-02
---

# Framing Point

The point in the frame the head should occupy: the **upper golden-ratio point**, horizontally centre
or a side point. In the vertical it is fixed at `y = 0.382` from the top for every profile.

## Sides

`SIDE_X` maps side → frame fraction: centre `0.5`, left `GOLDEN ≈ 0.382`, right `1 − GOLDEN`. The side
is chosen by the [face-direction rule](/rules/framing-golden-ratio.md).

## Use

The director inverts the framing point into camera angles with the current (or target) field of view,
including axis-invert switches, so the head lands exactly there on arrival.

# Citations
- [eagleeye/framing.py](/eagleeye/framing.py)
