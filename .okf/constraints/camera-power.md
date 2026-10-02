---
type: Constraint
title: Camera Needs External Power
description: The camera requires centre-negative 12 V DC power; without it the device is invisible to the host.
tags: [constraint, hardware, troubleshooting]
timestamp: 2026-10-02
---

# Camera Needs External 12 V Power

A physical constraint and the most common cause of "the system does not see my camera": the EagleEye IV
USB is **not powered over USB**.

## The requirement

- 12 V DC, at least 1.5 A (original supply 3.3 A), on a 5.5 mm barrel / 2.5 mm pin connector.
- **Polarity is centre-NEGATIVE** — the middle pin is minus. Measured at the connector, the centre pin
  reads −12 V relative to the sleeve.

## Why it matters to the software

Wrong polarity or a dead supply looks exactly like a software fault: no POWER LED, no `lsusb` entry, no
kernel log. `lsusb | grep 095d` should list the camera once powered. This belongs in troubleshooting
because no amount of code makes an unpowered camera appear.

# Citations
- [README.md](/README.md)
