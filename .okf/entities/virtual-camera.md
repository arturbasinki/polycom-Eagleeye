---
type: Entity
title: Virtual Camera
description: "The entity that owns the loopback output device, the frame writer thread and the slates."
tags: [virtual-camera, entity]
timestamp: 2026-10-02
---

# Virtual Camera

The engine entity that presents the application's image as a camera device named `EagleEye`. It owns a
writer thread that emits frames at a steady rate and a small status.

## State

- The connected source stream (or none) and the size derived from the "Resolution" setting.
- The last converted live frame and its age; privacy flag; the active light-correction LUT.
- The two slates (privacy, no-signal) rendered in the active UI language.
- The output device handle, status message and a write counter.

## Behaviour

- Writes at a fixed 30 fps; repeats the last frame until a new one arrives; falls back to the no-signal
  slate when the last frame is stale (or privacy's slate when privacy is on).
- Slates are never tone-corrected.
- A missing device or write error does not stop the thread; it retries after a delay.
- It releases the device to the [placeholder service](/domains/virtual-camera-and-privacy.md) when the
  app is not running, so receivers keep the camera.

# Citations
- [eagleeye/vcam.py](/eagleeye/vcam.py)
