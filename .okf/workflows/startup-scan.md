---
type: Workflow
title: Startup Scan
description: The scan-the-room workflow executed when tracking starts and on demand.
tags: [tracking, workflow, search]
timestamp: 2026-10-02
---

# Startup Scan

The workflow the camera follows when tracking starts: after power-on the head is parked (rear-facing,
lens down), so the app must look around before it can track.

## Steps

1. Zoom to the widest angle and tilt to the working height (the `home` preset tilt, or slightly below
   level if there is no home).
2. Build a plan of points every ~60° (the field of view is ~72°, so adjacent points overlap) up to the
   pan limits, starting from the **last known azimuth** — or `home` — because the person is most likely
   near where they were last seen.
3. Visit points in a **side-first** order (all points to the more open side, then the other), not
   alternating ±60°, which would require ever longer travels through the centre.
4. Pause at each point while **stationary** before deciding (detection in motion is blurred), then
   accept the first person found (with several people, the largest = nearest) and go to tracking.
5. If nobody is found, do a second row at a different height, then return home and rescan after a
   timeout (or on the "search" button).

## Two planners

- **Startup plan:** a full row, then back in a row offset upward.
- **Local plan:** the centre and one field of view to each side, used by the
  [loss ladder](/rules/target-loss-ladder.md) step 3.

# Citations
- [eagleeye/search.py](/eagleeye/search.py)
- [eagleeye/director.py](/eagleeye/director.py)
