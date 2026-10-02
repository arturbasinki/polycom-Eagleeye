---
type: Domain
title: Image Tuning and Light Correction
description: The subdomain of image controls and the one-shot face-driven tone-curve light correction.
tags: [domain, supporting, image, light]
timestamp: 2026-10-02
---

# Image Tuning and Light Correction

The supporting subdomain of making the picture look right: the camera's image controls (brightness,
contrast, saturation, hue, gamma, sharpness, white balance, backlight) plus a software **one-shot light
correction** that cannot be done in the camera.

## Why correction lives in software

The EagleEye IV has **no host-controllable exposure, iris or gain** — measured. Its auto-exposure meters
the whole frame, so a backlit person's face is too dark. Driving the camera's brightness/contrast/gamma
controls was measured to be insufficient. The correction is therefore a **256-entry tone LUT** applied
to the luma plane of the live output.

## The rule

One click measures the skin of the tracked person's face **once**, computes a gamma tone curve aiming
at a target skin luma, slope-limits it, anchors white back to 255, and applies it to the virtual camera
and preview until "restore defaults" or quit. It is **not** continuous and **not** persisted: lighting
changes day to day, so yesterday's curve would look like a bug.

See [the light correction rule](/rules/light-correction.md) and
[the flow](/data-flows/light-correction.md).

# Citations
- [eagleeye/lightfix.py](/eagleeye/lightfix.py)
- [eagleeye/engine.py](/eagleeye/engine.py)
- [docs/superpowers/specs/2026-10-01-subject-light-correction-design.md](/docs/superpowers/specs/2026-10-01-subject-light-correction-design.md)
