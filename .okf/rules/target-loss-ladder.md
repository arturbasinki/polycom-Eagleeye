---
type: BusinessRule
title: Target Loss Ladder
description: "The graduated response to losing the tracked person: catch-up, last azimuth, local search, home."
tags: [tracking, rule, recovery]
timestamp: 2026-10-02
---

# Target Loss Ladder

Business rule for what the camera does when the tracked person disappears. The camera never panics: it
reacts mildly first and only searches the room as a last resort. The depth of the ladder is
profile-dependent.

## Steps, mildest first

1. **Catch-up** — if the target vanished **at the frame edge** and the filter had velocity in that
   direction, make one predicted absolute pan move (last + velocity × horizon, capped) — talk only.
2. **Last azimuth** — set pan to the last known azimuth, tilt to its framing point, and wait. This is
   where the *talk* ladder ends.
3. **Local search** — after the step time, zoom out and scan ±1 field of view around the last azimuth
   (three points).
4. **Home** — if nothing is found, the camera returns to the `home` preset (or the loss point) and
   enters passive waiting; waiting always ends with a full rescan after a timeout.

## Rationale

In a conversation, a person leaving the frame is usually leaving the room or bending down — full
searching is wrong and restless. In a presentation, the person is expected to be somewhere in the
room, so the full ladder runs. The catch-up velocity estimate is deliberately distrusted in *talk*: it
fired 54–61° too far on real sessions.

# Citations
- [eagleeye/director.py](/eagleeye/director.py)
- [eagleeye/profiles.py](/eagleeye/profiles.py)
