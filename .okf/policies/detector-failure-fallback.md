---
type: Policy
title: Detector Failure Falls Back to CPU
description: Consecutive detector errors switch the pose model from GPU to CPU so tracking keeps working.
tags: [policy, reliability, perception]
timestamp: 2026-10-02
---

# Detector Failure Falls Back to CPU

Policy: a failing GPU detector must not stop tracking.

## When it fires

After a number of consecutive detector errors (five), the perception layer switches from the CUDA
execution provider to the CPU provider and reports it in the state.

## Behaviour

- Tracking continues; the loop rate drops (roughly 13–14 Hz instead of 15 Hz on the reference machine)
  but the product remains usable.
- GPU availability is reported to the UI (`unavailable` when `onnxruntime-gpu` or cuDNN is missing);
  the app still works without a GPU.

# Citations
- [eagleeye/tracker.py](/eagleeye/tracker.py)
- [eagleeye/detectors.py](/eagleeye/detectors.py)
- [README.md](/README.md)
