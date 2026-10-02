---
type: DomainEvent
title: Privacy Enabled
description: The event that privacy mode has been activated and the room is hidden.
tags: [privacy, event]
timestamp: 2026-10-02
---

# Privacy Enabled

The domain event raised when privacy mode becomes active.

## Trigger

`set_privacy(true)` from the tray, CLI or keyboard shortcut, while not already active.

## Follow-up

The output switches to the privacy slate, the current pose and tracking state are saved, tracking is
turned off, and the lens tilts fully down. The saved state is later consumed by the disable flow.

# Citations
- [eagleeye/privacy.py](/eagleeye/privacy.py)
