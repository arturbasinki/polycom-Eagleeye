---
type: BusinessRule
title: Framing on the Golden-Ratio Line
tags: [tracking, framing, rule]
timestamp: 2026-10-02
description: "The rule placing the head on the upper golden-ratio line, with a face-direction side, hysteresis and a 5% acceptance band."
---

# Framing on the Golden-Ratio Line

Business rule for *where* in the frame the head should be placed. It is independent of *when* the
camera moves, which the [dwell/hysteresis rules](/rules/dwell-and-hysteresis.md) govern.

## The rule

- **Vertical:** the head point sits on the upper golden-ratio line, `y = 0.382` from the top,
  for every profile and shot.
- **Horizontal:** with the face straight ahead the head is centred. After a sustained head turn the
  head moves to the **opposite** intersection so there is free space (*looking room*) in front of the
  face.
- **Side changes have their own hysteresis and dwell** (`SideSelector`): entering a side requires a
  sustained turn beyond an entry threshold; returning to centre requires a sustained turn below a
  lower exit threshold; switching side-to-side is direct but also dwell-gated, so a glance over the
  shoulder does not flip the frame.

## Acceptance band

A head at rest must stay within a **5 % band** around the framing point. The trigger zone (up to
15–26 %) is too wide to guarantee this, so an inner band plus a quiet re-fit after a few seconds
corrects slow displacement.

## Composition ties into zoom

The shot (CU / MCU / MS) sets how much of the frame height the eye→shoulder segment should occupy,
which yields the [auto-zoom goal](/rules/zoom-shot-selection.md).

# Citations
- [eagleeye/framing.py](/eagleeye/framing.py)
- [eagleeye/director.py](/eagleeye/director.py)
- [docs/superpowers/specs/2026-09-25-golden-framing-design.md](/docs/superpowers/specs/2026-09-25-golden-framing-design.md)
