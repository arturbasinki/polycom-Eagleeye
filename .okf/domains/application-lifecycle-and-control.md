---
type: Domain
title: Application Lifecycle and Control
description: "The domain of process lifecycle, background operation, remote control, single-instance locking and installation."
tags: [domain, supporting, lifecycle]
timestamp: 2026-10-02
---

# Application Lifecycle and Control

The domain of how the application runs and is controlled as a product: one process, a tray presence,
background operation, remote commands, single-instance locking, installation and uninstall.

## Model

- **One process** lives for the whole session. Closing the window **hides** it (to the tray); "Quit" in
  the tray ends everything. There is no separate daemon.
- A **UNIX socket** carries one-line JSON commands and doubles as the single-instance lock.
- A **tray icon process** and the **`eagleeye` CLI** are remotes over that socket.
- A `--user` **placeholder service** keeps the virtual camera alive when the app is not running.

## Shape decisions

- [Engine/UI separation](/decisions/engine-view-separation.md) keeps video flowing with the window
  closed; the split stays in the code even though the lifecycle is a single process.
- The [single instance is enforced by the socket](/rules/single-instance.md); a second launch just
  shows the existing window.

# Citations
- [eagleeye/engine.py](/eagleeye/engine.py)
- [eagleeye/control.py](/eagleeye/control.py)
- [eagleeye/cli.py](/eagleeye/cli.py)
- [eagleeye/trayproc.py](/eagleeye/trayproc.py)
