# rules

* [Dwell and Hysteresis](/rules/dwell-and-hysteresis.md) - The rule that the camera waits for a dwell outside a wide trigger zone and then arrives exactly at the framing point.
* [Framing on the Golden-Ratio Line](/rules/framing-golden-ratio.md) - The rule placing the head on the upper golden-ratio line, with a face-direction side, hysteresis and a 5% acceptance band.
* [UI Language Resolution](/rules/language-resolution.md) - How the interface language is detected, overridden, persisted and fallback-resolved.
* [Lead Only in Pan](/rules/lead-only-pan.md) - Predictive lead applies only to pan, and is capped in speed and reach; tilt never leads.
* [Light Correction](/rules/light-correction.md) - The rule for the one-shot, slope-limited gamma tone curve applied to skin, with reset-wins semantics.
* [Person Selection](/rules/person-selection.md) - How the chosen person is resolved, protected and eventually released back to automatic mode.
* [Search Scan](/rules/search-scan.md) - How search points are spaced, ordered and visited only while stationary.
* [Move Only Onto a Settled Target](/rules/settle-before-move.md) - The rule that the camera waits for a moving target to settle before an absolute move, unless it would escape the frame.
* [Single Instance via the Socket](/rules/single-instance.md) - Exactly one engine runs, enforced atomically by taking the control socket.
* [Target Loss Ladder](/rules/target-loss-ladder.md) - The graduated response to losing the tracked person: catch-up, last azimuth, local search, home.
* [Auto-Zoom Shot Selection](/rules/zoom-shot-selection.md) - How auto-zoom picks the shot size and moves only on a lasting, stable change.
