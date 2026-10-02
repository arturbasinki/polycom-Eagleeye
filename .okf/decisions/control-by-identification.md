---
type: Decision
title: Control by Identification
description: "The principle that motion bugs are fixed by measuring the plant and estimator, not by loosening thresholds."
tags: [decision, process, tracking]
timestamp: 2026-10-02
---

# Control by Identification

Decision (and standing process principle): motion problems are fixed by **measuring the plant and the
estimator**, never by widening zones or otherwise loosening thresholds.

## Context

Early tuning reached for zone sizes, `settle_time`, `max_target_jump_px`, smoothing and PID gains. Those
patches treated symptoms: the real issues were that the firmware already runs its own position
controller, that read-back lies, and that the target was the box centre rather than the head.

## Decision

- Identify the mechanism first: measure the camera's dynamics, zoom curve and trajectory, and the human
  motion noise; encode those as calibration.
- Express behaviour as explicit rules (dwell, hysteresis, settling, shot) on top of a truthful estimate,
  rather than as damping of a noisy signal.
- When a smoothness metric fails, tune profiles / filter settings / director constants and document the
  before-and-after measurement — do not change the metric's threshold.

## Consequences

- The estimate tells the truth about the target; whether to react is the [director](/entities/director.md)'s
  separate concern.
- Measurement tools (`measure_dynamics`, `measure_zoom`, `measure_trajectory`) and JSONL replay are
  first-class parts of the workflow.
- Threshold changes in simulation assertions require explicit agreement, because they are the contract.

# Citations
- [README.md](/README.md)
- [docs/superpowers/specs/2026-09-22-tracking-engine-design.md](/docs/superpowers/specs/2026-09-22-tracking-engine-design.md)
- [eagleeye/target_filter.py](/eagleeye/target_filter.py)
