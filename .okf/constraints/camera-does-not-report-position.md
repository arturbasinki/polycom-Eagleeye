---
type: Constraint
title: Camera Does Not Report Position
description: "Read-back returns the commanded value, so the real head angle must be modelled in software."
tags: [constraint, camera, measurement]
timestamp: 2026-10-02
---

# The Camera Does Not Report Where It Points

A measured constraint that shapes the whole tracking design: reading pan/tilt returns the **last
commanded value**, and during a velocity move the read-back does not change at all. There is no way to
ask the device where it is really looking.

## Consequences

- The app must maintain its own [head dynamics model](/entities/head-dynamics-model.md) and predict the
  real angle from the command history and measured firmware dynamics.
- World-angle conversion cannot trust a device read during motion; it uses the model's angle at the
  frame's exposure time.
- Without the model, "last azimuth" would be meaningless after any head movement and in-flight
  measurements would be biased by 3–4° in the direction of travel.

# Citations
- [eagleeye/head_model.py](/eagleeye/head_model.py)
- [README.md](/README.md)
