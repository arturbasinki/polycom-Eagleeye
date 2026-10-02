---
type: DomainEvent
title: Person Selected
description: The event that the operator has picked a person to follow.
tags: [identity, event, selection]
timestamp: 2026-10-02
---

# Person Selected

The domain event raised when the operator chooses a person to follow.

## Trigger

A click in the preview or `eagleeye select X,Y` that lands on a visible
[track](/entities/tracked-person.md).

## Follow-up

The selection state becomes *selected*; the chosen track becomes protected (survives a longer absence),
and the camera follows it. If it disappears, the event leads into the *suspended* waiting behaviour with
a hold timer; expiry returns to automatic mode.

# Citations
- [eagleeye/identity.py](/eagleeye/identity.py)
- [eagleeye/tracker.py](/eagleeye/tracker.py)
