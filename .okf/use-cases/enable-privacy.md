---
type: UseCase
title: Enable Privacy Mode
description: "The use case of hiding the room and pointing the lens down, then restoring the previous pose."
tags: [privacy, use-case]
timestamp: 2026-10-02
---

# Enable Privacy Mode

## Goal

One action hides the room from call participants and physically points the camera away, then restores
the previous state on exit.

## Main flow — enable

1. Switch the [virtual camera](/contracts/virtual-camera-output.md) to the privacy slate **immediately**
   (before the head moves) so callers never see the motion.
2. Remember the current tracking state and head pose.
3. Turn tracking off (the [privacy invariant](/invariants/tracking-off-in-privacy.md)).
4. Tilt the lens fully down.

## Main flow — disable

1. Move the head back to the saved pose **first**.
2. Then switch the virtual camera back to the live image.
3. Restore tracking if it was on (unless the app is shutting down, in which case the head still returns
   but tracking does not restart, so its velocity commands cannot interrupt the return).

## Invocation

The tray menu, `eagleeye privacy [on|off]`, and the GNOME keyboard shortcut **Super+Shift+C**.

# Citations
- [eagleeye/privacy.py](/eagleeye/privacy.py)
- [eagleeye/engine.py](/eagleeye/engine.py)
