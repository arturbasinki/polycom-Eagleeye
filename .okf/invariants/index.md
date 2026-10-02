# invariants

* [Head Calibration Lives in Code](/invariants/dynamics-calibration-in-code.md) - Measured camera calibration must live in code; config.json may only override it.
* [Single PTZ Writer](/invariants/single-ptz-writer.md) - Only the actuator may write the camera's motion controls, keeping the head model authoritative.
* [Tracking Off While Privacy On](/invariants/tracking-off-in-privacy.md) - Privacy mode and tracking cannot be active together; tracking is restored only on a normal exit.
* [Velocity Watchdog](/invariants/velocity-watchdog.md) - Velocity commands expire and are stopped by a watchdog thread if the loop hangs.
