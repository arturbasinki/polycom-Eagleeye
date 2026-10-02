---
type: ValueObject
title: Tracking Profile
description: "A named, immutable set of parameters that shapes tracking behaviour (talk / presentation)."
tags: [tracking, configuration]
timestamp: 2026-10-02
---

# Tracking Profile

An immutable, named set of behaviour parameters for [automatic tracking](/domains/automatic-tracking.md).
Two profiles ship: **talk** (calm: rare, smooth moves) and **presentation** (keep up with a walking
person; explicitly experimental).

## Fields that define a profile

- **Trigger zone** as a fraction of the field of view (pan and tilt), and **dwell** before moving.
- **Lead** (predictive offset) and **constant-speed follow** (pan only) with a speed threshold.
- **Target-loss ladder** depth and step time, and whether to catch up with a target lost at the edge.
- **Shot** (CU / MCU / MS) for auto-zoom, and the framing **side** thresholds and dwell.
- Whether measurements are **held during absolute moves** (talk: yes, to avoid 3–4° shift; walk:
  no, because a walking target must be seen in motion).

## Overrides

Only a whitelisted subset (`TUNABLE`) may be overridden from the UI's "advanced" section; overrides
never change identity, only parameters. Unknown or junk values fall back to the base profile.

## Starting values

| Parameter | talk | presentation |
|---|---|---|
| Trigger zone (pan / tilt) | ±15 % / ±12 % | ±26 % / ±12 % |
| Dwell | 0.8 s | 0.2 s |
| Lead | off | on (pan) |
| Follow | off | on from 8°/s |
| Loss ladder | step 2 | full ladder |
| Shot | MCU | MS |

# Citations
- [eagleeye/profiles.py](/eagleeye/profiles.py)
- [eagleeye/framing.py](/eagleeye/framing.py)
