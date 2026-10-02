---
type: BusinessRule
title: Person Selection
description: "How the chosen person is resolved, protected and eventually released back to automatic mode."
tags: [identity, rule, selection]
timestamp: 2026-10-02
---

# Person Selection

Business rule for click-to-follow: how the operator's chosen person is resolved and how the choice
behaves when that person vanishes.

## The rule

- A click (or `select X,Y`) resolves to the **visible** person whose box contains the point; on
  overlapping boxes, the one whose head is closer to the point. A click on nobody changes nothing.
- The chosen track is **protected**: it survives without a detection for the hold time (default 6 s)
  instead of the ordinary retention time.
- While suspended the camera **stays where the person vanished**; a stranger cannot steal the target.
- When the hold expires the selection returns to *auto* (the largest person). `select none` or "track
  automatically" clears it immediately.
- A suspended track is re-taken only with a clear **appearance** advantage over a rival, because after a
  few seconds position weighs little.

## Acceptance

After a click the camera keeps the chosen person through crossings; when the chosen person disappears it
waits rather than switching. Without a selection the behaviour is unchanged (the largest person).

# Citations
- [eagleeye/identity.py](/eagleeye/identity.py)
- [docs/superpowers/specs/2026-09-29-wybor-osoby-design.md](/docs/superpowers/specs/2026-09-29-wybor-osoby-design.md)
