---
type: UseCase
title: Replay a Session
description: The use case of recording tracking sessions and replaying them offline for diagnosis and tuning.
tags: [diagnostics, use-case, simulation]
timestamp: 2026-10-02
---

# Replay a Session

## Goal

Diagnose and re-tune tracking offline from a recorded session, and test closed-loop behaviour without
hardware.

## Main flow

1. Turn on **record session** (or start tracking with recording enabled); the tracker writes a JSONL
   row per step: time, world-angle measurement, commands, mode and framing.
2. Re-run offline with different settings:
   `.venv/bin/python tools/replay_session.py captures/sessions/<file>.jsonl --set dwell=1.2`.
3. Use the closed-loop [simulator](/eagleeye/sim.py) (camera + scene) to test director smoothness and
   search scenarios with the project's own metrics.

## Why recording is in world angles

World angles do not depend on camera movement, so a recorded session can be replayed against different
camera dynamics or tuning and still be meaningful — this is what makes "fix the mechanism, not the
thresholds" practical.

Sessions are ignored by git because they can show people and interiors.

# Citations
- [eagleeye/tracker.py](/eagleeye/tracker.py)
- [tools/replay_session.py](/tools/replay_session.py)
- [eagleeye/sim.py](/eagleeye/sim.py)
