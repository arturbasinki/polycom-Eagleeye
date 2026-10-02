---
type: Contract
title: Pose Detector Port
description: "The detector interface: frame in, scored boxes with COCO keypoints out, with backend metadata."
tags: [contract, perception, port]
timestamp: 2026-10-02
---

# Pose Detector Port

The internal interface between the [tracking loop](/workflows/tracking-loop.md) and the pose model: a
detector that turns a BGR frame into a list of [detections](/value-objects/detection.md) with keypoints.

## Shape

- `detect(frame_bgr) -> list[Detection]` with `keypoints` (17 COCO `(x,y,conf)` triples).
- Metadata: a backend description (`ONNX Runtime (CUDAExecutionProvider)` / CPU), a per-call duration, and
  a `gpu_error` note when GPU was requested but unavailable.

## Rules

- Preprocessing follows the model's spec: letterbox to 640×640 anchored top-left, padding 114, BGR, no
  normalization; NMS is applied on top of the model's own (as in the reference implementation).
- Score threshold and NMS threshold are configurable defaults.
- A detection is a plain value, not an identity; identity is supplied separately by
  [person tracking](/domains/person-identity.md).
- Backend selection wraps this port, so a CPU fallback changes nothing above it.

# Citations
- [eagleeye/detectors.py](/eagleeye/detectors.py)
- [eagleeye/perception.py](/eagleeye/perception.py)
