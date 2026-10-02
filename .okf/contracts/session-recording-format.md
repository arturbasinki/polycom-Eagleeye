---
type: Contract
title: Session Recording Format
description: "The JSONL session-recording format: time, world-angle measurement, commands, mode and framing."
tags: [contract, diagnostics, recording]
timestamp: 2026-10-02
---

# Session Recording Format

The on-disk format for recorded tracking sessions: one JSON object per line (JSONL), written to
`captures/sessions/<timestamp>.jsonl`.

## Row shape

```json
{"t": 12.3456, "world": [12345.0, -6789.0], "cmds": [["abs","pan",12000.0]], "mode": "tracking",
 "side": "center", "shot": "MCU"}
```

- `t` — loop time (seconds).
- `world` — the accepted world-angle measurement (pan, tilt) in arcseconds, or null.
- `cmds` — the commands emitted this step as `[kind, axis, value]`.
- `mode` — the director mode.
- Framing fields (side, shot, …) are added when available.

## Why

World angles do not depend on camera motion, so a session can be **replayed** against different dynamics
or tuning ([replay use case](/use-cases/replay-session.md)). Sessions are ignored by git because they can
show people and interiors.

# Citations
- [eagleeye/tracker.py](/eagleeye/tracker.py)
- [tools/replay_session.py](/tools/replay_session.py)
