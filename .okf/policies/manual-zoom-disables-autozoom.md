---
type: Policy
title: Manual Zoom Disables Auto-Zoom
description: A manual zoom change switches auto-zoom off until explicitly re-enabled.
tags: [policy, camera, zoom]
timestamp: 2026-10-02
---

# Manual Zoom Disables Auto-Zoom

Policy: a manual zoom change turns automatic zoom off **permanently** for the session until explicitly
re-enabled.

## When it fires

Any zoom change that did not come from the auto-zoom logic — the slider, the zoom buttons, recalling a
preset — detected by comparing the read-back zoom with the last commanded value while the optics are
still.

## Reaction

Auto-zoom is switched off; the operator re-enables it from the tracking panel or with
`eagleeye autozoom on`. The read-back is not judged while the optics are moving (the reading is
uncertain then and a difference is expected).

## Rationale

If the operator has deliberately chosen a zoom, the shot policy must not immediately fight that choice.
Making it an explicit re-enable keeps intent unambiguous.

# Citations
- [eagleeye/actuator.py](/eagleeye/actuator.py)
- [eagleeye/tracker.py](/eagleeye/tracker.py)
