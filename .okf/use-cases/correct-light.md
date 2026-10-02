---
type: UseCase
title: Correct the Light
description: The use case of measuring the face once and applying a scene-specific tone curve.
tags: [image, light, use-case]
timestamp: 2026-10-02
---

# Correct the Light

## Goal

Fix a badly lit face with one click, without continuous processing and without changing the camera's
own controls (which cannot fix it).

## Main flow

1. The operator presses **"Correct light"** in the Image card.
2. The engine grabs the latest **raw** camera frame and decodes it.
3. `lightfix.analyse` picks the person — the operator's selected person if any, otherwise the largest —
   finds a square around the visible head keypoints, and extracts **skin** luma with a YCrCb chroma mask
   (so hair, glasses and chair do not drag the median down).
4. If there is no frame/person/face/skin, report that specific outcome. If the face is within a dead
   zone of the target luma, the correction is removed ("already well lit").
5. Otherwise build a slope-limited gamma tone table, anchored so white stays at 255, and apply it to the
   virtual camera and the preview.
6. The table lives in memory until **"Restore defaults"** or quit.

## Alternative flows

- **Reset during measurement wins:** pressing "restore defaults" while the measurement is still running
  discards the result; a generation token guarantees the older measurement cannot re-apply a table.
- The preview while a correction is active shows the corrected output (converted back from the virtual
  camera's frame), not a separately corrected raw frame.

# Citations
- [eagleeye/engine.py](/eagleeye/engine.py)
- [eagleeye/lightfix.py](/eagleeye/lightfix.py)
- [eagleeye/vcam.py](/eagleeye/vcam.py)
