---
type: ExternalSystem
title: GNOME Desktop (Wayland)
description: "The external GNOME/Wayland desktop the app integrates with for tray, menu, shortcut and notifications."
tags: [context, external, desktop]
timestamp: 2026-10-02
---

# GNOME Desktop (Wayland)

The target desktop environment: Ubuntu with GNOME on Wayland, `ubuntu-appindicators` enabled. It is an
external system the app integrates with for its tray icon, menu entry, keyboard shortcut and
notifications.

## What the project uses from it

- **AyatanaAppIndicator3** for the system-tray icon, running in the *system* `python3` (with `python3-gi`)
  as a separate process — deliberately, to avoid fighting two event loops (Flet and GTK) in one process.
- A **GNOME application-menu entry** so the app starts like any desktop application.
- A **keyboard shortcut** (Super+Shift+C) bound to privacy mode.
- `notify-send` for desktop notifications when a shortcut-triggered command fails.
- XDG conventions for the runtime socket, the user's pictures directory, and autostart of the
  placeholder user service.

# Citations
- [tray/eagleeye_tray.py](/tray/eagleeye_tray.py)
- [install.sh](/install.sh)
- [eagleeye/config.py](/eagleeye/config.py)
