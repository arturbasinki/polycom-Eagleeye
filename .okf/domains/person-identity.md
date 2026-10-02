---
type: Domain
title: Person Identity
description: "The supporting subdomain that numbers people across frames and tracks the operator's chosen person."
tags: [domain, supporting, identity]
timestamp: 2026-10-02
---

# Person Identity

The supporting subdomain that gives people stable **numbers** across frames and tracks which one the
operator has chosen. RTMO-s returns a fresh list of people each frame with no memory; this domain
supplies the memory.

## Model

- A [tracked person](/entities/tracked-person.md) lives in world angles, with an appearance feature
  (an HSV histogram of the torso between shoulders and hips) and an alpha-beta position filter.
- Distances and the position gate are measured in **body heights**, so thresholds do not depend on
  zoom or distance.
- Detections are matched to tracks by a **greedy** assignment (not Hungarian — SciPy is deliberately
  not a dependency) with a cost blending position, size and appearance.

## Selection

The operator's choice is a small state machine: *auto* → *selected* ↔ *suspended* → *auto*. A
selected person who vanishes keeps the camera waiting in place for a hold time (default 6 s) before
automatic mode resumes; a stranger cannot steal the target while the choice is suspended. See the
[person selection rule](/rules/person-selection.md).

## Deliberate non-goals

No re-identification network, no face recognition, no new model. Appearance matching is enough for
crossings and short disappearances; it only fails when two people wear identical clothing.

# Citations
- [eagleeye/identity.py](/eagleeye/identity.py)
- [docs/superpowers/specs/2026-09-29-wybor-osoby-design.md](/docs/superpowers/specs/2026-09-29-wybor-osoby-design.md)
