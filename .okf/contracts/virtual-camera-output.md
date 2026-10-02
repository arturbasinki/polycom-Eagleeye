---
type: Contract
title: Virtual Camera Output Contract
description: "The I420, camera-sized, fixed-rate device-format and slate behaviour contract with conferencing apps."
tags: [contract, virtual-camera]
timestamp: 2026-10-02
---

# Virtual Camera Output Contract

The format and behaviour the `EagleEye` device must present to conferencing apps.

## Format

- Pixel format **I420 (YU12)**, full-range BT.601 luma/chroma, packed planes (Y, then U, then V).
- **The camera's size** (the "Resolution" setting) at a **steady 30 fps**; dimensions even. Changing
  the resolution reopens the device at the new size. Never a fixed or reduced size: the Resolution
  setting is the quality floor for the call image (see
  [Full Quality, Waste Removed](/quality/full-quality-no-waste.md)).
- Luma may have a light-correction LUT applied; colour is subsampled at the end.

## Behaviour

- The writer emits a frame every period regardless of camera pauses, repeating the last frame.
- Slates: privacy (when privacy is on), and "no signal" when the last frame is older than ~1 s or the
  camera is disconnected. Slates are rendered by Pillow (so Polish glyphs work), localized, and
  re-rendered at the output size when it changes.
- A missing device or write error does not stop the thread; it retries after ~1 s.
- The device is released to the placeholder service when the app is not running.

## Consumers

Chrome/Meet, Teams, Zoom and OBS must be able to select the device; see
[the consumer requirements](/external/conferencing-apps.md) and
[exclusive_caps](/constraints/v4l2loopback-exclusive-caps.md).

# Citations
- [eagleeye/vcam.py](/eagleeye/vcam.py)
- [eagleeye/v4l2.py](/eagleeye/v4l2.py)
