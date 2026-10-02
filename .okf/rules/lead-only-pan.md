---
type: BusinessRule
title: Lead Only in Pan
description: "Predictive lead applies only to pan, and is capped in speed and reach; tilt never leads."
tags: [tracking, rule, motion]
timestamp: 2026-10-02
---

# Lead Only in Pan

Business rule that restricts predictive offset to the horizontal axis.

## The rule

When a profile enables lead (presentation), the camera may aim **ahead** of the target only in **pan**.
The lead is `v × (latency + half the move duration)`, capped in both speed (≈25°/s) and reach (a
fraction of the frame width, e.g. a quarter), so a fast close-up motion cannot fire a ±110° command.

Tilt never leads: vertical "velocity" is mostly nodding and leaning. Leading it fired the tilt past the
target and a second move brought it back.

## Why

Walking is horizontal, so lead helps pan stay ahead of a walking person. Vertical motion is transient,
so predicting it produces overshoot and extra moves rather than smoothness.

# Citations
- [eagleeye/director.py](/eagleeye/director.py)
- [eagleeye/profiles.py](/eagleeye/profiles.py)
