---
type: DataFlow
title: Light Correction Flow
description: The data flow from frame and face to the tone LUT and its application in the virtual camera.
tags: [data-flow, image, light]
timestamp: 2026-10-02
---

# Light Correction Flow

How the tone curve is computed and where it goes.

## Flow

1. The engine fetches the latest **raw** camera frame and decodes it.
2. `analyse` chooses the target person (selected person if any, else the largest), crops a square around
   the visible head keypoints, and extracts **skin** luma with a YCrCb chroma mask.
3. The median skin luma → gamma → a 256-entry LUT (slope-limited, white anchored).
4. The LUT is stored on the engine and handed to the [virtual camera](/entities/virtual-camera.md), which
   applies it to the luma plane on the next conversion and forces a re-conversion.
5. The preview, when the correction is active, shows the corrected output re-encoded from the virtual
   camera's frame (cheaper than correcting the raw frame separately).

## Destinations

- Virtual-camera live frames (not slates), via `vcam.set_tone`.
- In-app preview, via `vcam.live_frame()` re-encoded to JPEG.

# Citations
- [eagleeye/engine.py](/eagleeye/engine.py)
- [eagleeye/lightfix.py](/eagleeye/lightfix.py)
- [eagleeye/vcam.py](/eagleeye/vcam.py)
