---
type: System
title: EagleEye Control
description: "The product as a whole: a Linux desktop application that drives a Polycom EagleEye IV PTZ camera and auto-frames the tracked person for conferencing apps."
resource: /README.md
tags: [context, product]
timestamp: 2026-10-02
---

# EagleEye Control

EagleEye Control turns a Polycom EagleEye IV USB camera on Linux into a camera that follows
people by itself. It is an independent community project, not affiliated with Polycom or HP.

## Purpose and responsibilities

- Expose full **PTZ**, zoom, focus, image tuning and **camera presets** for the physical camera.
- Run **automatic person tracking** that frames the subject's head like a calm camera operator.
- Publish the already-framed image on a **virtual camera** (`EagleEye`) so Google Meet, Microsoft
  Teams, Zoom and OBS receive it.
- Provide a one-shortcut **privacy mode** (a slate for callers, lens tilted down).
- Keep capturing and tracking while the window is hidden; expose control through a system-tray
  icon and an `eagleeye` CLI.

## Shape of the system

The product is split into a window-independent [engine](/contexts/engine.md) and thin
[views and remotes](/contexts/view-and-control.md): the tray icon and the CLI talk to it over a UNIX
socket, the Flet window runs in the engine's process and calls it directly. The whole design rests on
one principle: [track in world angles, not pixels](/decisions/track-in-world-angles.md).

## Scope boundaries

The physical camera, the `v4l2loopback` kernel module, the RTMO-s pose model and the desktop
environment are external systems the project depends on, not part of it.

# Citations
- [README.md](/README.md)
- [app.py](/app.py)
- [eagleeye/engine.py](/eagleeye/engine.py)
