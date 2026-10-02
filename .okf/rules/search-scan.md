---
type: BusinessRule
title: Search Scan
description: "How search points are spaced, ordered and visited only while stationary."
tags: [tracking, rule, search]
timestamp: 2026-10-02
---

# Search Scan

Business rule for how the camera looks around when it has no target.

## The rule

- Points are spaced **~60°** because the field of view is ~72°, so adjacent views overlap.
- Ordering is **start, then all points to the side with more range, then the other side** — not
  alternating ±60°, which would force ever longer travels through the centre (a full row would take
  ~48 s instead of ~24 s).
- A point is decided **only while stationary**, after a short rest, because detection during motion is
  unreliable (at ~27°/s and 30 fps the image shifts ~16 px/frame and faces blur).
- Full scan: one row at the working height, then a second row slightly higher.
- Local search: the loss point and one field of view to each side.

## Rationale

Scanning is a fallback, not the normal state. It is bounded in time (~10 s for a full scan), always
returns somewhere sensible, and in the *talk* profile it is not part of the loss ladder at all.

# Citations
- [eagleeye/search.py](/eagleeye/search.py)
- [eagleeye/director.py](/eagleeye/director.py)
