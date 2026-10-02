---
type: Decision
title: Decode Once to YUV Planes
description: "The decision to decode MJPEG once, straight to shared 4:2:0 planes with TurboJPEG, and make the CPU sleep while the GPU infers."
tags: [decision, performance, encoding]
timestamp: 2026-10-02
---

# Decode Once to YUV Planes

Decision: decode each camera MJPEG frame **once**, straight to Y/Cb/Cr 4:2:0 planes with **TurboJPEG**
(ctypes binding to the TurboJPEG 2.x API), share those read-only planes between the virtual camera and
the tracker, and switch the CUDA primary context to **blocking sync** so the CPU sleeps instead of
spinning while the GPU infers.

## Context

Live app, 1920×1080 MJPEG at 30 fps, tracking on (`top -H`, 2026-10-02): the `vcam` thread used ~34 % of
one core and the `tracker` thread ~34 % (`loop_ms` 22.2). Isolated benchmarks on a real 1080p camera
frame:

| Step | Wall | CPU |
|---|---|---|
| `vcam.jpeg_to_i420` (Pillow → YCbCr → split → chroma resize) | 10.3–12.2 ms | same |
| Tracker `decode_mjpeg_scaled(jpg, 2)` (a second decode of the same frame) | 6.0 ms | |
| ORT `session.run` on CUDA, default scheduling | 9.0–9.5 ms | **9.1–9.6 ms (spin-wait)** |
| ORT `session.run`, primary context `CU_CTX_SCHED_BLOCKING_SYNC` | 9.8–10.0 ms | **5.3 ms** |
| TurboJPEG `tjDecompressToYUVPlanes` | **3.7 ms** | same |
| TurboJPEG planes → I420 bytes | 4.1 ms | same |

TurboJPEG luma is byte-identical to Pillow's; the chroma is the camera's own (the old path upsampled and
re-downsampled it). The camera pads frames before the JPEG EOI marker: TurboJPEG reports that as a
warning with no stderr output, while OpenCV's libjpeg prints `Corrupt JPEG data` on every frame (still
true in OpenCV 5.0).

## Decision

- **TurboJPEG straight to planes.** A small ctypes binding to `libturbojpeg.so.0` using the stable 2.x
  API; the JPEG's own Y plane is the luma, and chroma is reduced to 4:2:0 only when the camera sent 4:2:2
  or 4:4:4 (grayscale gets neutral chroma).
- **One decode, shared read-only.** A `FrameDecoder` keeps the latest frame per source and hands the same
  immutable planes to the virtual camera and the tracker; the light-correction LUT is applied to a copy
  of the Y plane for the call image only, so the tracker and the next light measurement see the raw frame.
- **Blocking sync.** The CUDA driver API (`cuDevicePrimaryCtxSetFlags_v2`, `CU_CTX_SCHED_BLOCKING_SYNC`)
  is set before ONNX Runtime creates its session; best-effort, so a missing driver or GPU is harmless.
- **Pillow fallback.** Without `libturbojpeg0` the app runs on Pillow with the same luma and logs one
  warning. Pillow also stays the decoder for the one-shot light measurement.

## Alternatives rejected

- **OpenCV `cv2.imdecode`** — its libjpeg prints `Corrupt JPEG data` to stderr on every frame of this
  camera (re-verified with OpenCV 5.0), and it does not decode to planes.
- **`simplejpeg`** — no YUV-plane decode.
- **`PyTurboJPEG` 2.x** — requires TurboJPEG 3 (`tj3Init`); the Ubuntu archive ships 2.1.5.
- **nvJPEG** — a GPU dependency for the call image, and a CPU fallback would still be needed.
- **Rewriting the engine in C++** — Python glue is ~3.6 ms per tracker iteration (~5 % of one core) and
  the same C libraries already do the work.

## Consequences

- Adds the `libturbojpeg0` system package (installer and README); no new pip dependency. The app keeps
  working without it, on Pillow.
- The image is unchanged: same luma, the camera's own chroma; no resolution, frame rate or JPEG quality
  is touched — see [Full Quality, Waste Removed](/quality/full-quality-no-waste.md).
- Supersedes [Decode MJPEG with Pillow](/decisions/pillow-over-opencv-decoding.md) for the per-frame path.
- **Measured live on 2026-10-02** (same machine and session, 1920×1080 MJPEG at 30 fps, tracking on,
  profile `talk`, window visible, `libturbojpeg.so.0` loaded; `top -H` over 10 s, before → after):

  | | Before | After |
  |---|---|---|
  | `vcam` thread | 24.1 % | **9.4 %** |
  | `tracker` thread | 30.5 % | **13.9 %** |
  | `loop_ms` | 22–30 | **10–16** |
  | `detection_ms` | 11–15 | 8–12 (one 18.9 right after start) |
  | Loop rate | 14.7–14.9 Hz | 14.9–15.6 Hz |

  The engine's two hot threads went from ~55 % to ~23 % of one core. The virtual camera's frame read
  back from `/dev/video10` is 1920×1080 with natural colours. The Flet window process is unchanged
  (~210 % across its threads while visible) — the next step is the
  [Qt Quick View](/decisions/qt-quick-view-future.md), not the engine.

# Citations
- [eagleeye/jpeg.py](/eagleeye/jpeg.py)
- [eagleeye/frames.py](/eagleeye/frames.py)
- [eagleeye/detectors.py](/eagleeye/detectors.py)
