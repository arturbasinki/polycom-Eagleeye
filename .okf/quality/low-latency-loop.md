---
type: QualityAttribute
title: Low-Latency Tracking Loop
description: "The non-functional requirement that perception and decoding stay inside the loop's time budget."
tags: [quality, performance, nfr]
timestamp: 2026-10-02
---

# Low-Latency Tracking Loop

The quality attribute that keeps the tracking loop inside its time budget: ~15 Hz, with detection and
decoding fast enough that the target estimate is fresh when the director uses it.

## Targets and techniques

- **Pose inference** ~8–10 ms on the reference GPU (960×540 frame, measured 2026-10-02), ~62 ms on CPU.
  The CUDA primary context is set to **blocking sync**, so the CPU sleeps instead of spinning while the
  GPU infers (CPU 5.3 ms instead of ~9.5 ms per inference, measured 2026-10-02).
- **Decode once to planes**: each MJPEG frame is decoded once with TurboJPEG straight to Y/Cb/Cr (~4 ms
  per 1080p frame) and shared read-only by the virtual camera and the tracker; the detector's half-size
  BGR is built from those planes ([Decode Once to YUV Planes](/decisions/decode-once-to-yuv-planes.md)).
- **No preview recompression** while no light correction is active: raw MJPEG bytes go straight to the
  preview widget, and detection overlays are drawn by the widget over it, never baked into the image.
  With a correction active, the corrected virtual-camera frame is encoded to JPEG once.
- **Separate file descriptors** for the stream and the controls, so a control write never disturbs
  capture.
- The loop measures and exposes Hz, detection/loop time and frame age for diagnosis (2026-10-02 at
  1080p: loop 22 ms, detection 11 ms, frame age ~24 ms).

## Why it is a quality requirement

The world-angle model and Kalman filter assume a frame's exposure time is known and close to now. A
slow loop widens the prediction horizon and degrades framing; the app also competes for CPU with the
call, so the budget is a product constraint — met by removing waste, never by lowering resolution or
rate (see [Full Quality, Waste Removed](/quality/full-quality-no-waste.md)).

# Citations
- [README.md](/README.md)
- [eagleeye/tracker.py](/eagleeye/tracker.py)
- [eagleeye/detectors.py](/eagleeye/detectors.py)
