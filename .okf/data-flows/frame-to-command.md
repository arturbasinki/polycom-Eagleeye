---
type: DataFlow
title: Frame to Command
description: "The end-to-end data flow from an MJPEG frame through pose, world angles and filtering to PTZ commands."
tags: [data-flow, tracking, pipeline]
timestamp: 2026-10-02
---

# Frame to Command (Tracking Pipeline)

How a single camera frame becomes camera motion.

## Sources and stores

- **Source:** the physical camera MJPEG stream (`/dev/video0`), decoded with Pillow.
- **Model state:** the head model (real camera angle), the Kalman filter (target in world angles).

## Flow

1. MJPEG frame + V4L2 timestamp → decode (half scale) → **RTMO-s** → detections with keypoints.
2. Detections → [head point](/terms/head-point.md), face yaw, head scale; tracks updated
   ([identity](/domains/person-identity.md)) and the target chosen.
3. The observation's pixel point → **world angle** using the camera angle from the
   [head model](/entities/head-dynamics-model.md) at the frame time and the zoom-scale factor.
4. World angle + yaw + scale → **Kalman filter** → [target estimate](/value-objects/target-estimate.md)
   (position and velocity, with motion-dependent variance).
5. Estimate + head model + view → [director](/entities/director.md) → list of
   [commands](/value-objects/ptz-command.md).
6. Commands → **actuator** → V4L2 ioctl writes; the head model is updated.
7. The same frame (raw JPEG) is also handed to the [virtual camera](/data-flows/virtual-camera-output.md)
   for output.

## Notes

- Measurements from frames taken during an absolute move are down-weighted (extra variance from camera
  speed × timing error + model error), and may be held entirely in the talk profile.
- Camera velocity for that weighting is derived from the head model's angle difference around the frame
  time.

# Citations
- [eagleeye/core.py](/eagleeye/core.py)
- [eagleeye/tracker.py](/eagleeye/tracker.py)
- [eagleeye/perception.py](/eagleeye/perception.py)
- [eagleeye/target_filter.py](/eagleeye/target_filter.py)
