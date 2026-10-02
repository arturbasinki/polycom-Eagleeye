---
type: DomainEvent
title: Target Lost
description: "The event that the tracked person has not been measured for too long, triggering the loss ladder."
tags: [tracking, event]
timestamp: 2026-10-02
---

# Target Lost

The domain event raised when the [Kalman filter](/value-objects/target-estimate.md) has gone too long
without an accepted measurement — by default ~0.4 s.

## Trigger

No accepted head measurement within `lost_after`, or a run of rejected measurements whose reset time
has also elapsed. Measurements taken while the camera moves are not "accepted" at full weight, and a
profile may deliberately **hold** the last position during its own absolute move or a zoom move, so the
camera does not declare loss on account of its own motion.

## Follow-up

The [director](/entities/director.md) reacts with the
[target loss ladder](/rules/target-loss-ladder.md): catch-up (talk), last azimuth, local search, home.
The camera's own absolute arrival can briefly lose detection; the director finishes its planned move
before announcing loss, to avoid interrupting its own travel.

# Citations
- [eagleeye/target_filter.py](/eagleeye/target_filter.py)
- [eagleeye/director.py](/eagleeye/director.py)
