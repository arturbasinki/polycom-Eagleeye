---
type: BoundedContext
title: View and Control
tags: [context, architecture, ui]
timestamp: 2026-10-02
description: "The bounded context of the window, tray and CLI: the tray and CLI as socket remotes, the window as an in-process view."
---

# View and Control

The bounded context of everything that talks *to* the engine without owning hardware: the Flet
desktop window, the system-tray icon process, and the `eagleeye` command-line. They are views and
remotes; a camera or tracking state never lives here.

## Responsibility

- Render the engine's [state](/contracts/control-socket.md) (preview, PTZ, optics, image, tracking
  panel, people and selection, performance) and forward user intent as commands.
- Show the preview from the virtual camera's point of view — the preview must display the same image
  that goes to Zoom, and detection overlays are drawn **only** in the preview, never in the call image.
- Closing the window **hides** it (to the tray); it does not stop the engine.

## Two kinds of client

- **Remote clients — tray icon and CLI.** Separate processes. They speak only the
  [one-line JSON control protocol](/contracts/control-socket.md) (the CLI is described in
  [`eagleeye` CLI](/contracts/cli-command.md)).
- **In-process view — the window.** It runs in the engine's process (see
  [Single Process with a Tray Lifecycle](/decisions/single-process-tray-lifecycle.md)) and holds a
  reference to the engine object: it calls engine methods directly and reads the camera stream and the
  virtual camera's current frame for the preview. It does not use the socket.

## Preview source

- Normally the preview shows the camera's raw MJPEG frame, unchanged — the same picture the virtual
  camera converts for the call, without a re-encode.
- While a light correction is active it shows the virtual camera's already corrected I420 frame,
  encoded to JPEG once for the widget, so the preview matches the call image.

## Boundary

No client opens a camera descriptor or runs a tracker of its own. The window's direct access is wide
today (stream, tracker, virtual camera and engine methods); a narrow engine facade for it is the
precondition for swapping the UI toolkit — see [Qt Quick View](/decisions/qt-quick-view-future.md).
This separation is what lets video keep flowing while the window is closed.

# Citations
- [app.py](/app.py)
- [tray/eagleeye_tray.py](/tray/eagleeye_tray.py)
- [eagleeye/cli.py](/eagleeye/cli.py)
- [eagleeye/engine.py](/eagleeye/engine.py)
- [docs/superpowers/specs/2026-09-23-productization-design.md](/docs/superpowers/specs/2026-09-23-productization-design.md)
