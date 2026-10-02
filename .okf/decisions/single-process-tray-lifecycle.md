---
type: Decision
title: Single Process with a Tray Lifecycle
description: The decision to run a single tray-resident process with the engine/UI split kept inside it.
tags: [decision, lifecycle, architecture]
timestamp: 2026-10-02
---

# Single Process with a Tray Lifecycle

Decision: the product is **one process**, started from the menu, that keeps running in the system tray
when the window is closed; "Quit" in the tray ends everything. No separate daemon, no autostart.

## Context

Uses are video calls and recording, with a full control panel. The engine must run without the window,
which could have justified a daemon, but the target user is one person on their own machine.

## Decision

- Start the engine and the window in one process; closing the window only **hides** it.
- Keep the engine/UI **split in code** so the engine could become a daemon without a redesign.
- A separate **tray process** (system `python3` + AyatanaAppIndicator) sends commands over the socket,
  avoiding two competing event loops (Flet and GTK) in one process.
- A separate `--user` **placeholder service** keeps the virtual camera alive when the app is off.

## Alternatives rejected

- Autostart with the session, or an "run at login" switch (the user chose on-demand).
- Starting on demand when a client opens `/dev/video10` (v2l2loopback does not announce a new reader).
- A separate daemon with inter-process communication (unnecessary complexity for one machine).

# Citations
- [docs/superpowers/specs/2026-09-22-tracking-engine-design.md](/docs/superpowers/specs/2026-09-22-tracking-engine-design.md)
- [eagleeye/trayproc.py](/eagleeye/trayproc.py)
- [eagleeye/engine.py](/eagleeye/engine.py)
