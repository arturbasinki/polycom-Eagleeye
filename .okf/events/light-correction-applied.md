---
type: DomainEvent
title: Light Correction Applied
description: The event that a tone curve has been accepted and applied to the output.
tags: [image, light, event]
timestamp: 2026-10-02
---

# Light Correction Applied

The domain event raised when a newly computed tone curve has been accepted and applied.

## Trigger

A successful one-shot measurement whose status is `ok` (a face darker or brighter than the dead zone),
and whose generation token still matches — i.e. no reset happened during the measurement.

## Follow-up

The LUT replaces any previous one on the engine and the virtual camera and is applied to the luma plane
of subsequent live output; the preview shows the corrected frame. A `well_lit` result instead raises the
removal of any existing correction.

# Citations
- [eagleeye/engine.py](/eagleeye/engine.py)
- [eagleeye/lightfix.py](/eagleeye/lightfix.py)
