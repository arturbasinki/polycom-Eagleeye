---
type: DataFlow
title: Settings and Presets Flow
description: How settings and presets are applied to live objects and persisted atomically.
tags: [data-flow, configuration]
timestamp: 2026-10-02
---

# Settings and Presets Flow

How user settings and camera presets move through the system.

## Flow

1. The window (or a command) requests a change (profile, language, home, auto-zoom, recording,
   select-hold, preset).
2. The [engine](/contexts/engine.md) applies it to the live objects (tracker, director, virtual camera)
   and, for persisted settings, writes through the [Store](/contracts/config-json.md).
3. `Store.save` writes atomically; the file is created on first save and is not committed.
4. The UI renders the resulting [state](/contracts/control-socket.md) from the engine, so all clients
   agree on the current values.

## Notes

- `dynamics` is special: it is an **override** of the in-code calibration, written by measurement tools.
- `profile` changes reset per-profile overrides; only the whitelisted `TUNABLE` fields can be overridden.
- Presets store complete poses (pan, tilt, zoom, focus, focus-auto) and are upserted by name.

# Citations
- [eagleeye/config.py](/eagleeye/config.py)
- [eagleeye/engine.py](/eagleeye/engine.py)
- [app.py](/app.py)
