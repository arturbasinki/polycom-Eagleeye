---
type: DomainEvent
title: Target Acquired
description: The event that a target is found again and the director returns to tracking.
tags: [tracking, event]
timestamp: 2026-10-02
---

# Target Acquired

The domain event raised when the director stops searching or waiting and has a usable target again,
entering the `tracking` mode.

## Trigger

- A search visit found a person (largest = nearest, when several), or
- In `lost`/`waiting`, a new accepted estimate arrives while the head is not moving.

## Follow-up

- The loss ladder resets to zero and any search plan is discarded.
- The auto-zoom state is either restored (if zoom had been temporarily widened) or re-derived from the
  composition shot.
- The composition side selector and per-axis machines restart fresh.

# Citations
- [eagleeye/director.py](/eagleeye/director.py)
