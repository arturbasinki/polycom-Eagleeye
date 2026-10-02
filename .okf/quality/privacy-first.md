---
type: QualityAttribute
title: Privacy First
description: The non-functional requirement that privacy never leaks the room image or motion to callers.
tags: [quality, privacy, nfr]
timestamp: 2026-10-02
---

# Privacy First

The quality attribute behind privacy mode: at no point should call participants see the room between
enabling privacy and the lens moving away, or vice versa.

## How it is met

- The output switches to the slate **before** the head moves when enabling.
- The head returns to the saved pose **before** the live image reappears when disabling.
- Tracking is off while privacy is active, so the head cannot wander behind the slate.
- On shutdown with privacy on, the head is restored first so the next start does not face the floor.

## Verification

Privacy behaviour (slate, order of operations, restore pose, tracking state) is covered by dedicated
tests including the engine and the virtual camera.

# Citations
- [eagleeye/privacy.py](/eagleeye/privacy.py)
- [eagleeye/engine.py](/eagleeye/engine.py)
- [tests/test_privacy.py](/tests/test_privacy.py)
