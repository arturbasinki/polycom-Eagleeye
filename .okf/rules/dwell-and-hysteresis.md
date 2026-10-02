---
type: BusinessRule
title: Dwell and Hysteresis
tags: [tracking, rule, motion]
timestamp: 2026-10-02
description: The rule that the camera waits for a dwell outside a wide trigger zone and then arrives exactly at the framing point.
---

# Dwell and Hysteresis

Business rule governing *when* the camera moves. It is the primary source of the "calm operator"
feel: the camera reacts to a **large** deviation, then arrives exactly at the framing point, and small
wobble around the point produces no movement.

## The rule

- The camera wakes when the head leaves the **trigger zone** (a fraction of the field of view, so it
  scales with zoom) and the head stays outside continuously for a **dwell** time.
- On a move, the camera arrives exactly at the framing point.
- Inside the trigger zone there is a smaller **composition band** (5 %). A head that settles outside
  the band but inside the zone is corrected by a quiet **re-fit** only after a few seconds.
- In-flight correction only happens on a large deviation after about 60 % of the move has completed —
  restarting the S-curve halfway would be the worst jerk.

## Why

A single "dead zone" caused moves on its edge (jitter). Hysteresis between the wide trigger zone and
the exact arrival point is what makes motion rare and smooth; the inner band keeps a settled head
correctly composed without the zone being permanently armed.

# Citations
- [eagleeye/director.py](/eagleeye/director.py)
- [eagleeye/profiles.py](/eagleeye/profiles.py)
