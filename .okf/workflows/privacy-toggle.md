---
type: Workflow
title: Privacy Toggle
description: "The ordered steps for entering and leaving privacy mode, including shutdown handling."
tags: [privacy, workflow]
timestamp: 2026-10-02
---

# Privacy Toggle

The ordering-sensitive workflow that changes the visible output and the head together.

## Steps (enable)

1. Set the output to the privacy **slate**.
2. Save the current pose and tracking state.
3. Disable tracking.
4. Tilt the lens down.

## Steps (disable)

1. Command the head back to the saved pose.
2. Wait (on full shutdown, up to a few seconds) for the head model to say it has arrived.
3. Re-enable tracking if it was on and a resume was requested.
4. Set the output back to the live image.

## On application shutdown

If privacy is active when the app quits, it restores the head position before closing devices —
otherwise the next start would find the lens pointing at the floor. Tracking is explicitly **not**
restarted in this path.

# Citations
- [eagleeye/privacy.py](/eagleeye/privacy.py)
- [eagleeye/engine.py](/eagleeye/engine.py)
