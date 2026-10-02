---
type: ValueObject
title: Detection
description: "A pose-model output: a scored box with optional keypoints, in original frame coordinates."
tags: [perception, value-object]
timestamp: 2026-10-02
---

# Detection

A value object produced by the pose model: a bounding box with a score, a label, and optionally the
COCO pose keypoints, all in the **original frame's** coordinate system.

## Shape

- `x, y, w, h` (box) and `score`; `label` (e.g. the model name).
- `keypoints`: 17 `(x, y, confidence)` triples from the pose model, or None.
- Derived: `center`, `area`, `as_box()`.

## Role

The detection is the raw perception output. It is **not** an identity: it has no memory between frames.
The [head point](/terms/head-point.md), face yaw and head scale are derived from it, and the
[tracker](/domains/person-identity.md) turns detections into persistent
[tracked people](/entities/tracked-person.md).

# Citations
- [eagleeye/detectors.py](/eagleeye/detectors.py)
- [eagleeye/perception.py](/eagleeye/perception.py)
