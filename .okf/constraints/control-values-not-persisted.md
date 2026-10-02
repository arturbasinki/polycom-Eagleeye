---
type: Constraint
title: Camera Control Values Do Not Persist
description: The camera does not retain control values; only application presets in config.json persist.
tags: [constraint, camera, persistence]
timestamp: 2026-10-02
---

# Camera Control Values Do Not Persist

A constraint: the camera does not retain control settings across power cycles or reconnects. Only the
application's own [presets](/value-objects/camera-preset.md) in `config.json` survive.

## Consequences

- On every open, the engine re-applies or re-reads what it needs; presets are the only durable poses.
- A "rotate the image in-camera" style toggle would not survive a restart and is therefore not offered
  (the image-flip service control exists but is unused — see the measured-quirks notes).
- Firmware cannot be updated from Linux, so no device-side fix is possible.

# Citations
- [README.md](/README.md)
- [eagleeye/engine.py](/eagleeye/engine.py)
- [eagleeye/config.py](/eagleeye/config.py)
