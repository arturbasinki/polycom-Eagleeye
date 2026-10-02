---
type: BusinessRule
title: Single Instance via the Socket
description: "Exactly one engine runs, enforced atomically by taking the control socket."
tags: [rule, lifecycle, control]
timestamp: 2026-10-02
---

# Single Instance via the Socket

Business rule that exactly one engine runs per user session.

## The rule

- Taking the control socket is **atomic** (`bind` succeeds for exactly one process); the loser gets
  `EADDRINUSE`.
- If a live instance answers on the socket, the newcomer refuses to start and behaves as a client: bare
  `eagleeye` sends `show` to the existing window.
- A socket left by a crashed process (nobody answers) is removed and the new instance proceeds.

## Why

Two engines would fight over the single V4L2 stream and the same virtual-camera device. Atomic bind is
simpler and more robust than a PID file.

# Citations
- [eagleeye/control.py](/eagleeye/control.py)
- [eagleeye/cli.py](/eagleeye/cli.py)
