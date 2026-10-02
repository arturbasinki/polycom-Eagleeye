---
type: Decision
title: One Pose Model Instead of Two Detectors
description: The decision to replace face+body detectors with one keypoint pose model to stop posture-change jumps.
tags: [decision, perception, ml]
timestamp: 2026-10-02
---

# One Pose Model Instead of Two Detectors

Decision: use a single multi-person pose model, **RTMO-s**, whose 17 keypoints supply the head point in
every posture, replacing the earlier face (YuNet) + body (YOLOX) pair.

## Context

Two detectors required selecting one, and switching between face and body when someone stood up, sat
down or turned shifted the target by **9–13°** — visible as a jump and a corrective camera move. The
face model also only sees the front of the head.

## Decision

- One one-stage pose model over ONNX Runtime (CUDA or CPU).
- Build the head point from nose/eyes/ears, and additionally derive face yaw and the eye→shoulder scale
  from the same keypoints.

## Consequences

- The same clip shows at most 3–5° shift on posture change; keypoints exist from the back too.
- The torso keypoints also provide the appearance feature for [person identity](/domains/person-identity.md),
  so no extra model is needed.
- GPU is preferred, CPU fallback via the [detector policy](/policies/detector-failure-fallback.md).

# Citations
- [docs/superpowers/specs/2026-09-22-tracking-engine-design.md](/docs/superpowers/specs/2026-09-22-tracking-engine-design.md)
- [eagleeye/detectors.py](/eagleeye/detectors.py)
- [eagleeye/perception.py](/eagleeye/perception.py)
