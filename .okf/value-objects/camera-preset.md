---
type: ValueObject
title: Camera Preset
description: A named full camera pose (pan/tilt/zoom/focus) stored in config.json and recallable.
tags: [camera, configuration, presets]
timestamp: 2026-10-02
---

# Camera Preset

A stored, named camera pose: pan, tilt, zoom and focus plus the focus-auto mode. Presets are the
operator's waypoints and include the special `home` preset the camera returns to when nobody is around.

## Identity

Identity is the **name**; saving with an existing name updates that preset (upsert). The `home` preset is
not a list entry but a setting (`tracking.home`) used by the [loss ladder](/rules/target-loss-ladder.md)
and [startup scan](/workflows/startup-scan.md).

## State

Integer control values for pan, tilt, zoom, focus and `focus_auto` (1 = auto). Stored in
[config.json](/contracts/config-json.md).

## Behaviour

Recalling a preset moves the head and optics to the stored pose. If it changes zoom, it counts as a
[manual zoom](/policies/manual-zoom-disables-autozoom.md).

# Citations
- [eagleeye/config.py](/eagleeye/config.py)
- [app.py](/app.py)
