---
type: UseCase
title: Select Person to Follow
description: The use case where the operator picks one person for the camera to follow.
tags: [identity, use-case, selection]
timestamp: 2026-10-02
---

# Select Person to Follow

## Goal

With several people in view, the operator makes the camera follow **one specific person**, and that
choice survives crossings and brief disappearances.

## Main flow — select by click

1. The operator clicks a person in the preview (or runs `eagleeye select X,Y`).
2. The engine resolves the frame point to the visible [track](/entities/tracked-person.md) whose box
   contains it (on overlap, the one with the closer head).
3. The selection state becomes *selected*; that track is protected from removal for the hold time.
4. While the selected person is seen the camera follows them.
5. If they vanish, the selection becomes *suspended*: the camera waits where they vanished for
   `select_hold_s` (default 6 s) rather than jumping to a stranger.
6. If the hold expires, selection returns to *auto* (the largest person).

## Alternative flow — back to automatic

`eagleeye select none`, or the "track automatically" control, clears the selection and returns to
following the largest person (no regressions to the pre-selection behaviour).

## Business value

Without identity, the target jumps to another person at a crossing or occlusion and the app "goes
dumb"; click-to-follow fixes exactly that.

# Citations
- [eagleeye/identity.py](/eagleeye/identity.py)
- [eagleeye/tracker.py](/eagleeye/tracker.py)
- [eagleeye/engine.py](/eagleeye/engine.py)
- [docs/superpowers/specs/2026-09-29-wybor-osoby-design.md](/docs/superpowers/specs/2026-09-29-wybor-osoby-design.md)
