---
type: Decision
title: One-Shot Light Correction
description: "The decision to correct light with a one-shot, in-memory, face-driven tone curve rather than auto-exposure."
tags: [decision, image, light]
timestamp: 2026-10-02
---

# One-Shot Light Correction Instead of Auto-Exposure

Decision: correct a badly lit face with a **single, on-request tone curve** computed from the person's
skin, not with continuous auto-exposure, not by driving camera controls, and not persisted.

## Context

The camera has no host-controllable exposure/iris/gain and meters the whole frame, so a backlit face is
dark. The app is already CPU-heavy (pose inference), so per-frame analysis is undesirable. Driving
brightness/contrast/gamma was measured to be insufficient.

## Decision

- A "Correct light" button measures the face **once**, builds a 256-entry LUT, and applies it.
- "Restore defaults" (or quit) removes it; a reset during measurement wins.
- The correction lives in memory only.

## Alternatives rejected

- Continuous/automatic regulation and re-measuring after the click.
- Persisting the correction across restarts (lighting changes; yesterday's curve looks like a bug).
- Camera brightness/contrast/gamma control (insufficient) and exposure/iris control (nonexistent).

# Citations
- [docs/superpowers/specs/2026-10-01-subject-light-correction-design.md](/docs/superpowers/specs/2026-10-01-subject-light-correction-design.md)
- [eagleeye/lightfix.py](/eagleeye/lightfix.py)
