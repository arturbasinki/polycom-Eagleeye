---
type: Decision
title: Frame on the Golden Ratio
description: The decision to place the head on the golden-ratio line with a face-direction side and shot-based zoom.
tags: [decision, framing]
timestamp: 2026-10-02
---

# Frame on the Golden Ratio

Decision: compose the shot on the golden-ratio line rather than the frame centre or a per-profile head
height.

## Context

The director originally placed the head in a trigger zone around a framing point whose vertical position
was a per-profile `head_height` (0.375 talk, 0.30 presentation), and the zoom was set by the user. The
request was composition based on framing rules: face on the upper left/right third, shot filled
according to plan, which requires zoom control.

## Decision

- Vertical framing fixed on the upper **golden-ratio line** (`y = 0.382`) for all profiles.
- Horizontal side chosen by **face direction** — free space in front of the face — with hysteresis and
  dwell, centre when facing forward.
- A per-profile **shot** (CU/MCU/MS) that auto-zoom realises.
- An inner **composition band** with a quiet re-fit so a settled head stays correctly composed.

## Consequences

- Framing no longer depends on profile head height; pan and tilt use the same vertical rule.
- Auto-zoom becomes a first-class axis with its own band, dwell and stability gate to avoid pumping.
- Shot selection (`shot_for`) is left as the extension point for future situation-aware framing.

# Citations
- [docs/superpowers/specs/2026-09-25-golden-framing-design.md](/docs/superpowers/specs/2026-09-25-golden-framing-design.md)
- [eagleeye/framing.py](/eagleeye/framing.py)
