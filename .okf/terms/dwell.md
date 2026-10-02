---
type: Term
title: Dwell
description: The continuous time a head must be outside the trigger zone before the camera reacts.
tags: [glossary, tracking, motion]
timestamp: 2026-10-02
---

# Dwell

The time the head must stay **continuously** outside the trigger zone before the camera moves. It is the
patience ingredient of the calm-operator feel.

## Values

Per profile: talk 0.8 s, presentation 0.2 s. Related timers: the search rest at a scan point, the zoom
dwell (longer than pan/tilt so leaning in does not zoom), and the side-change dwell.

## Interaction with other rules

Dwell is suspended only for the escape condition in [settle-before-move](/rules/settle-before-move.md)
(a moving target that would leave the frame). A brief excursion inside the dwell leaves the axis idle —
this is what makes a person fidgeting not produce camera moves.

# Citations
- [eagleeye/director.py](/eagleeye/director.py)
- [eagleeye/profiles.py](/eagleeye/profiles.py)
