---
type: Decision
title: Separate Engine from View
description: "The decision to keep a hardware-owning engine independent of all UI: socket remotes plus an in-process window."
tags: [decision, architecture]
timestamp: 2026-10-02
---

# Separate Engine from View

Decision: split the application into a window-independent **engine** (camera, tracking, virtual camera,
privacy) and thin **views** (Flet window, tray icon, CLI). The tray icon and the CLI are separate
processes that talk to the engine over a UNIX socket; the window lives in the engine's process and
calls it directly.

## Context

Video must keep flowing when the window is closed so Zoom/Meet/OBS still receive a picture, and the
panel preview must show what is actually sent to the call. The old `CameraApp` owned both the camera
and the UI in one object.

## Decision

- Create `Engine`, which lives for the whole process and owns all hardware and long-running state.
- Make the window, tray and CLI views/remotes; closing the window only hides it.
- Tray and CLI use the [control socket](/contracts/control-socket.md); the window, being in-process,
  uses the engine object (see [View and Control](/contexts/view-and-control.md)).
- Have the preview show the picture the virtual camera outputs, with detection overlays drawn only there.

## Consequences

- The engine can later become a daemon without redesign, though today the product is a
  [single process](/decisions/single-process-tray-lifecycle.md) with a tray.
- Views can be tested against a controller interface without hardware; `app.py` holds presentation only.
- State for the UI is one immutable, atomically-replaced snapshot, avoiding many lock-guarded fields.
- The window's in-process access is broader than the socket protocol (it reads the stream and the
  virtual camera's frame directly) — fine for one process, but it ties the window to engine internals.

# Citations
- [docs/superpowers/specs/2026-09-23-productization-design.md](/docs/superpowers/specs/2026-09-23-productization-design.md)
- [eagleeye/engine.py](/eagleeye/engine.py)
- [app.py](/app.py)
