---
type: Entity
title: Tracked Person (Track)
description: "A person tracked across frames: stable id, world-angle position, appearance feature and lifecycle."
resource: /eagleeye/identity.py
tags: [identity, entity, tracking]
timestamp: 2026-10-02
---

# Tracked Person (Track)

An identity-bearing entity: one physical person followed across frames. It is *not* a detection — it
survives the frames and travels in world angles.

## Identity

A monotonically increasing integer id, assigned when a detection spawns a new track and kept stable
while the person remains identifiable. Identity is what lets the operator
[select a person](/use-cases/select-person.md) and keep following *that* person.

## State

- Head point in [world angles](/terms/world-angle.md) and a size in world arcseconds (body height), so
  thresholds are scale-free.
- Velocity (alpha-beta filtered) and an appearance feature: an HSV histogram of the torso.
- `last_seen`, `misses`, and the last known pixel box/head for the UI.
- **Visible** (matched in this frame) vs **suspended** (not matched; kept alive for a short time, or
  longer if it is the selected person).

## Lifecycle

Spawned by an unmatched detection, updated by an accepted match, suspended on a miss, and removed when
it has been unseen beyond its retention time (extended for the protected selected id).

# Citations
- [eagleeye/identity.py](/eagleeye/identity.py)
