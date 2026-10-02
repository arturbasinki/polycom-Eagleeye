---
type: Term
title: Shot
description: A named framing size (CU/MCU/MS) defined by the fraction of frame height the eye→shoulder span fills.
tags: [glossary, framing, zoom]
timestamp: 2026-10-02
---

# Shot

A named camera framing size — close-up (**CU**), medium close-up (**MCU**) or medium shot (**MS**) —
expressed as the fraction of the frame height the **eye→shoulder segment** should occupy.

## Values

`SHOTS = {CU: 0.56, MCU: 0.36, MS: 0.19}`, calibrated on the real camera (MCU raised so the bottom edge
sits at half the chest rather than the solar plexus).

## Role

Each [tracking profile](/value-objects/tracking-profile.md) carries a default shot (talk: MCU,
presentation: MS), and the [auto-zoom rule](/rules/zoom-shot-selection.md) converts the shot into a zoom
goal. Shot selection is the documented extension point for future "smart framing" (choosing the shot
from the situation, e.g. sitting / standing / walking).

# Citations
- [eagleeye/framing.py](/eagleeye/framing.py)
- [eagleeye/profiles.py](/eagleeye/profiles.py)
