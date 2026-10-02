---
type: Term
title: Head Point
tags: [glossary, tracking, perception]
timestamp: 2026-10-02
description: "The mean of the visible head keypoints (nose, eyes, ears), with a top-edge fallback, that tracking aims at."
---

# Head Point

The single point per person that the tracker aims at, computed as the mean of the *visible* nose, eye
and ear keypoints (COCO indices 0–4) of the RTMO-s pose. It exists from the front, in profile,
standing and from behind.

## Fallback rule

If none of those head keypoints is visible (for example the head is above the frame for someone
standing close to the camera), the head point falls back to the centre of the **top edge** of the
detection box — so the camera is asked to move up rather than "losing" the person.

## Why not the box centre

An operator frames on the **head** (upper third), while the centre of a body box jumps as the person
sits, stands or gesticulates. Aiming at the head point is what removes that jitter; the earlier design
that used the box centre caused visible hunting.

# Citations
- [eagleeye/perception.py](/eagleeye/perception.py)
