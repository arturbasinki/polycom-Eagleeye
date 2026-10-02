# decisions

* [Control by Identification](/decisions/control-by-identification.md) - The principle that motion bugs are fixed by measuring the plant and estimator, not by loosening thresholds.
* [Decode Once to YUV Planes](/decisions/decode-once-to-yuv-planes.md) - The decision to decode MJPEG once, straight to shared 4:2:0 planes with TurboJPEG, and make the CPU sleep while the GPU infers.
* [Separate Engine from View](/decisions/engine-view-separation.md) - The decision to keep a hardware-owning engine independent of all UI: socket remotes plus an in-process window.
* [English Codebase, Multilingual UI](/decisions/english-codebase-multilingual-ui.md) - The decision to make the codebase English and move all user-visible text into runtime catalogs.
* [Frame on the Golden Ratio](/decisions/golden-ratio-framing.md) - The decision to place the head on the golden-ratio line with a face-direction side and shot-based zoom.
* [Greedy Identity with Appearance, Not Re-ID](/decisions/greedy-identity-with-appearance.md) - The decision to use greedy matching plus torso colour appearance instead of a re-ID network or Hungarian assignment.
* [One-Shot Light Correction](/decisions/one-shot-light-correction.md) - The decision to correct light with a one-shot, in-memory, face-driven tone curve rather than auto-exposure.
* [Decode MJPEG with Pillow](/decisions/pillow-over-opencv-decoding.md) - The decision to decode MJPEG with Pillow to silence libjpeg warnings; superseded for the per-frame path by Decode Once to YUV Planes, kept as the fallback and the one-shot light-measurement decoder.
* [Qt Quick View (Proposed, Future)](/decisions/qt-quick-view-future.md) - A proposed, unscheduled direction: replace the Flet window with Qt Quick via PySide6 while keeping the Python engine.
* [One Pose Model Instead of Two Detectors](/decisions/single-pose-model-rtmo.md) - The decision to replace face+body detectors with one keypoint pose model to stop posture-change jumps.
* [Single Process with a Tray Lifecycle](/decisions/single-process-tray-lifecycle.md) - The decision to run a single tray-resident process with the engine/UI split kept inside it.
* [Track in World Angles, Not Pixels](/decisions/track-in-world-angles.md) - The decision to convert detections to world angles so camera motion cancels out of measurements.
