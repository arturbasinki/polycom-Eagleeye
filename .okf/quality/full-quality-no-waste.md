---
type: QualityAttribute
title: "Full Quality, Waste Removed"
description: The non-functional requirement that the camera is used at full chosen quality and CPU is saved only by removing waste.
tags: [quality, performance, nfr]
timestamp: 2026-10-02
---

# Full Quality, Waste Removed

The non-functional requirement that the camera is used at its full chosen quality, and that CPU cost is
reduced only by removing waste.

## The requirement

- The **"Resolution" setting is the quality floor** for both the call image (virtual camera) and the
  in-app preview. Neither is silently scaled down or fixed to a smaller size.
- Frame rates (camera, virtual camera, preview) and JPEG quality are never lowered, capped or made
  adaptive to save CPU.
- CPU cost is reduced by finding and removing waste: double decodes, double colour conversions,
  re-encoding, busy waiting (thread-pool spin, GPU spin-wait), toolkit overhead.

## How performance work proceeds

1. Profile the live app first (per-thread CPU, then isolated per-step benchmarks).
2. Remove the waste at its origin and measure again on the live app.
3. If a real hardware or toolkit limit remains, explain it with numbers and offer architectural
   options (e.g. [Qt Quick View](/decisions/qt-quick-view-future.md)) — not quality cuts.

## Why

The product's point is full-quality use of the camera in calls; trading quality for CPU is perceived as
breaking the app. The virtual camera output was once found silently fixed at 1280×720 while the
Resolution control said 1080p; it was treated as a defect and fixed.

## Related

- [Low-Latency Tracking Loop](/quality/low-latency-loop.md)
- [Virtual Camera Output Contract](/contracts/virtual-camera-output.md)

# Citations
- [eagleeye/vcam.py](/eagleeye/vcam.py)
- [app.py](/app.py)
