---
type: Invariant
title: Tracking Off While Privacy On
description: Privacy mode and tracking cannot be active together; tracking is restored only on a normal exit.
tags: [invariant, privacy, tracking]
timestamp: 2026-10-02
---

# Tracking Is Off While Privacy Is On

An invariant enforced by the engine: while [privacy mode](/entities/privacy-mode.md) is active,
automatic tracking is disabled, and requesting tracking while privacy is on is rejected.

## Why

Privacy promises callers a slate and a lens pointing down. A tracker that could run behind the slate
would defeat the promise and could move the head away from the parked position. Enabling tracking also
returns a localized error (`engine.error.privacy_on`) instead of silently doing nothing.

Enabling privacy with tracking on saves the state, turns tracking off, and restores it only on exit
(and never on shutdown).

# Citations
- [eagleeye/engine.py](/eagleeye/engine.py)
- [eagleeye/privacy.py](/eagleeye/privacy.py)
