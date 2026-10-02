---
type: Actor
title: Camera Operator
description: "The local human user who starts the app, tunes the camera, chooses who to follow and toggles privacy."
tags: [context, actor]
timestamp: 2026-10-02
---

# Camera Operator

The operator is the person at the machine. The application is primarily built for the repository
owner's own use, then for anyone who clones the repository and runs the installer.

## Goals and interactions

- Start the app from the desktop menu; closing the window should hide it, not stop tracking.
- Adjust camera position, optics and image settings; save and recall [presets](/value-objects/camera-preset.md).
- Turn [auto-tracking](/domains/automatic-tracking.md) on and off and choose a
  [tracking profile](/value-objects/tracking-profile.md) (talk / presentation).
- When several people are in view, [click the one to follow](/use-cases/select-person.md).
- Toggle privacy mode with a single shortcut (Super+Shift+C).
- [Correct the light](/use-cases/correct-light.md) for the current scene with one click.
- Control a running instance from the command line or the tray without a terminal.

The operator is also the calibrator: measured hardware values for a given unit are produced with the
project's measurement tools and become the [in-code calibration](/invariants/dynamics-calibration-in-code.md).

# Citations
- [README.md](/README.md)
- [eagleeye/cli.py](/eagleeye/cli.py)
- [app.py](/app.py)
