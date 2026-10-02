---
type: UseCase
title: Save/Recall a Preset
description: "The use case of storing and recalling full camera poses, including the home pose."
tags: [camera, use-case, presets]
timestamp: 2026-10-02
---

# Save/Recall a Preset

## Goal

Store a complete camera pose and return to it later with one action.

## Main flow

1. The operator frames the shot (pan, tilt, zoom, focus).
2. Saving stores a named [preset](/value-objects/camera-preset.md) — pan, tilt, zoom, focus and
   focus-auto mode — in `config.json` (upsert by name).
3. Recalling moves the head to the stored pose and restores optics.
4. "Set home" stores the pose the camera returns to when nobody is around; it is used by the
   [loss ladder](/rules/target-loss-ladder.md) and the [startup scan](/workflows/startup-scan.md).

## Notes

- Recalling a preset that changed zoom counts as a [manual zoom](/policies/manual-zoom-disables-autozoom.md).
- Camera control values do not persist in the device; only presets in `config.json` do.
- Presets are written atomically so the file cannot be corrupted.

# Citations
- [eagleeye/config.py](/eagleeye/config.py)
- [app.py](/app.py)
