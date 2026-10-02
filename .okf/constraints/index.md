# constraints

* [Camera Does Not Report Position](/constraints/camera-does-not-report-position.md) - Read-back returns the commanded value, so the real head angle must be modelled in software.
* [Camera Needs External Power](/constraints/camera-power.md) - The camera requires centre-negative 12 V DC power; without it the device is invisible to the host.
* [Camera Control Values Do Not Persist](/constraints/control-values-not-persisted.md) - The camera does not retain control values; only application presets in config.json persist.
* [No Host-Controllable Exposure](/constraints/no-host-exposure-control.md) - The camera exposes no exposure/iris control, so backlit faces must be corrected in software.
* [V4L2 Single Stream Reader](/constraints/v4l2-single-reader.md) - A V4L2 stream may be read by only one process, which forces the virtual-camera architecture.
* [v4l2loopback exclusive_caps](/constraints/v4l2loopback-exclusive-caps.md) - The loopback device must be declared with exclusive_caps=1 for browsers to treat it as a camera.
