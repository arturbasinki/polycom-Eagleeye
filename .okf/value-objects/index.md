# value-objects

* [Camera Preset](/value-objects/camera-preset.md) - A named full camera pose (pan/tilt/zoom/focus) stored in config.json and recallable.
* [Detection](/value-objects/detection.md) - A pose-model output: a scored box with optional keypoints, in original frame coordinates.
* [Field of View (View)](/value-objects/field-of-view.md) - The immutable field-of-view and pixel↔world-angle conversion value used throughout tracking.
* [Observation](/value-objects/observation.md) - The per-frame head measurement in pixels plus capture time, yaw and head scale.
* [PTZ Command](/value-objects/ptz-command.md) - An immutable camera-movement instruction (absolute, velocity or zoom) passed from decision to actuator.
* [Target Estimate](/value-objects/target-estimate.md) - The filtered target position, velocity and attributes in world angles that the director consumes.
* [Tracking Profile](/value-objects/tracking-profile.md) - A named, immutable set of parameters that shapes tracking behaviour (talk / presentation).
