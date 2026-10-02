---
type: Decision
title: "Greedy Identity with Appearance, Not Re-ID"
description: The decision to use greedy matching plus torso colour appearance instead of a re-ID network or Hungarian assignment.
tags: [decision, identity, algorithm]
timestamp: 2026-10-02
---

# Greedy Identity with Appearance, Not Re-ID

Decision: give people stable numbers across frames with a **greedy** assignment whose cost blends
position, size and a **torso colour histogram** — no Hungarian algorithm, no re-identification network,
no face recognition.

## Context

After adding click-to-follow, the target jumped to another person at a crossing, occlusion or brief
loss. A full re-ID model or a Hungarian assignment were considered.

## Decision

- Match detections to tracks greedily by lowest cost (position + size + appearance), with a motion gate
  that grows with absence and an appearance threshold.
- Use an HSV torso histogram from RTMO-s shoulder/hip keypoints as the appearance feature, mixed across
  frames.
- Keep distances in **body heights** so thresholds are zoom- and distance-independent.

## Consequences

- Cost is microseconds per person; no new dependency (SciPy is deliberately absent).
- Works except when two people wear identical clothing; a re-ID network is deferred until measurements
  show this variant is insufficient.
- A suspended track is re-taken only with a clear appearance advantage, so position cannot decide
  between lookalikes.

# Citations
- [eagleeye/identity.py](/eagleeye/identity.py)
- [docs/superpowers/specs/2026-09-29-wybor-osoby-design.md](/docs/superpowers/specs/2026-09-29-wybor-osoby-design.md)
