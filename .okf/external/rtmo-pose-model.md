---
type: ExternalSystem
title: RTMO-s Pose Model
description: The external pose-estimation model that supplies all person detections and keypoints.
tags: [context, external, perception, ml]
timestamp: 2026-10-02
---

# RTMO-s Pose Model

A single **one-stage multi-person pose** model (OpenMMLab, Apache-2.0) run through ONNX Runtime, giving
17 COCO keypoints per person. It is downloaded by the installer (~36 MB) and is not part of the
repository.

## Why one model replaced two detectors

The project previously ran a face detector (YuNet) plus a body detector (YOLOX). Switching between
them moved the target by **9–13°** whenever someone stood up, sat down or turned. RTMO-s yields a head
point in **every** posture (front, profile, standing, from behind) and keeps the shift within 3–5° on
the same clip.

## Properties the design leans on

- **Keypoints are first-class**: the head point is built from nose/eyes/ears, face yaw from the nose
  relative to the eyes/ears, and head scale from the eye→shoulder segment.
- **Torso keypoints** (shoulders, hips) feed the appearance histogram for
  [person identity](/domains/person-identity.md).
- Runs on CUDA by default at ~7.8 ms per 960×540 frame on the reference GPU, ~62 ms on CPU; the loop
  falls back to CPU after consecutive detector errors.

# Citations
- [eagleeye/detectors.py](/eagleeye/detectors.py)
- [eagleeye/perception.py](/eagleeye/perception.py)
- [models/](/models)
