---
type: Invariant
title: Velocity Watchdog
description: Velocity commands expire and are stopped by a watchdog thread if the loop hangs.
tags: [invariant, safety, camera]
timestamp: 2026-10-02
---

# Velocity Watchdog

A safety invariant: every velocity command is valid only for a short deadline (≈300 ms), and a separate
lightweight thread stops any axis whose velocity has not been refreshed.

## Why

A hung tracking loop must never leave the camera turning on its own. A velocity write has no natural
end; without a watchdog a frozen program means a spinning camera.

## How it is kept

- Writing a velocity sets a per-axis deadline; the loop refreshes it each tick while the follow
  decision stands.
- The watchdog thread checks deadlines every 50 ms and writes a stop if one has expired.
- The trakking loop stopping cleanly also zeroes all velocities and stops the watchdog.

# Citations
- [eagleeye/actuator.py](/eagleeye/actuator.py)
