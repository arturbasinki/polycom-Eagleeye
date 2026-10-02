---
type: BoundedContext
title: Engine
description: "The window-independent core: it owns the camera, tracking, virtual camera and privacy, and lives for the whole process lifetime."
tags: [context, architecture]
timestamp: 2026-10-02
---

# Engine

The engine is the bounded context that owns all hardware and long-running state. The Flet window,
the tray icon and the `eagleeye ...` commands are only views and remotes for it; the engine keeps
running when the window is hidden.

## Responsibility

- Own the camera stream and control device, the [tracker](/entities/tracker.md), the
  [virtual camera](/entities/virtual-camera.md) and the [privacy](/entities/privacy-mode.md) state.
- Reconnect when another program holds the camera, and fall back from GPU to CPU on detector
  failures.
- Apply the [light correction](/rules/light-correction.md) and expose the current
  [state](/contracts/control-socket.md) to callers.

## Boundary

Inside the engine, a model is consistent: the camera head angle is modelled in
[world angles](/terms/world-angle.md), the target is filtered once, and only the
[actuator](/invariants/single-ptz-writer.md) writes PTZ. Outside it, clients speak a one-line JSON
protocol over a UNIX socket and never touch the device directly.

# Citations
- [eagleeye/engine.py](/eagleeye/engine.py)
- [eagleeye/control.py](/eagleeye/control.py)
- [docs/superpowers/specs/2026-09-23-productization-design.md](/docs/superpowers/specs/2026-09-23-productization-design.md)
