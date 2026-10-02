---
type: UseCase
title: Enable/Disable Auto-Tracking
description: "The use case of starting and stopping automatic tracking, including the startup search."
tags: [tracking, use-case]
timestamp: 2026-10-02
---

# Enable/Disable Auto-Tracking

## Goal

The operator turns automatic tracking on or off; the camera then follows people (or stops and stays
put).

## Main flow — enable

1. Reject if there is no camera, or if privacy mode is active.
2. Refresh the zoom reading (it may have changed via a slider or preset) and reset the target filter
   and person identities.
3. Start a **search** from the last known azimuth (or home) — see [search scan](/rules/search-scan.md).
4. Optionally start recording the session to a JSONL file.
5. Publish the new state to all clients.

## Main flow — disable

1. Stop all velocity moves.
2. Reset the director to *waiting* and clear identities.
3. Close the session recording if one is open.

## Alternative flows

- Camera held by another program (e.g. Meet picked the physical camera): the engine keeps retrying to
  open it and tracking resumes by itself.
- GPU detector fails repeatedly: fall back to CPU and say so in the state.

# Citations
- [eagleeye/tracker.py](/eagleeye/tracker.py)
- [eagleeye/engine.py](/eagleeye/engine.py)
