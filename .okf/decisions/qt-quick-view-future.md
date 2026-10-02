---
type: Decision
title: "Qt Quick View (Proposed, Future)"
description: "A proposed, unscheduled direction: replace the Flet window with Qt Quick via PySide6 while keeping the Python engine."
tags: [decision, ui, performance, proposed]
timestamp: 2026-10-02
---

# Qt Quick View (Proposed, Future)

Status: **proposed — not decided, not scheduled.** A recorded direction for the next performance step
after the engine's waste is removed.

## Context

- The engine is C libraries (libjpeg, OpenCV, ONNX Runtime) driven by Python; Python glue is ~3.6 ms per
  tracker iteration (~5 % of one core, measured 2026-10-02). A C++ rewrite of the engine would save
  about that and re-open calibrated, live-verified behaviour — rejected.
- The window is the expensive part Python cannot fix. Flet's Flutter GTK3 embedder, at 125 % fractional
  scaling on a large monitor, renders at 2×, reads every frame back from GL and composites it on the UI
  thread — 80–90 % of that thread at 30 fps, growing with window area (measured 2026-09-25). The `flet`
  process averaged 45 % of a core over a 24-minute session (2026-10-02). The preview also travels as
  JPEG → base64 → Flet protocol → decode in Dart.

## Proposal

Replace the Flet window with **Qt Quick (QML) through PySide6**, keeping the Python engine:

- native Wayland rendering with fractional scaling (Qt ≥ 6.5), no GL readback;
- the preview as `VideoOutput` fed the virtual camera's I420 frame (`QVideoFrame` YUV420P, colour
  conversion in a GPU shader) — the preview becomes literally the call image, with no extra decode or
  encode;
- detection overlays as QML items over the video.

## Preconditions

1. A narrow engine facade for the in-process window (state snapshot, commands, frame subscription)
   instead of today's direct access to the stream, tracker and virtual camera
   (see [View and Control](/contexts/view-and-control.md)).
2. `app.py` split by panel while porting.

## Acceptance (when taken up)

Same features and i18n; preview at the full Resolution and the camera's fps
([Full Quality, Waste Removed](/quality/full-quality-no-waste.md)); UI-thread CPU at 125 % scaling,
window maximised, measured against the Flet baseline.

# Citations
- [app.py](/app.py)
- [docs/superpowers/plans/2026-10-02-cpu-waste-removal.md](/docs/superpowers/plans/2026-10-02-cpu-waste-removal.md)
