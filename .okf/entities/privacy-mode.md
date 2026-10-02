---
type: Entity
title: Privacy Mode
description: The entity that remembers the pre-privacy pose and tracking state and coordinates the ordered switch.
tags: [privacy, entity]
timestamp: 2026-10-02
---

# Privacy Mode

The engine entity coordinating the hidden state: whether privacy is active and the pose/tracking state
saved when it was turned on.

## State

- `active` flag.
- `saved_pose` (pan, tilt) from before privacy was enabled, or None with no camera.
- `saved_tracking` — whether tracking was on and should resume.

## Behaviour

- **Enable:** slate on → save pose/tracking → disable tracking → tilt fully down.
- **Disable:** move back to the saved pose → resume tracking (unless shutting down) → slate off.
- A paused/idempotent enable or disable does nothing.

See the [workflow](/workflows/privacy-toggle.md) and the [invariant](/invariants/tracking-off-in-privacy.md).

# Citations
- [eagleeye/privacy.py](/eagleeye/privacy.py)
