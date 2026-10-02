# contracts

* [Camera Controls Contract](/contracts/camera-controls.md) - The V4L2 control IDs and rules through which the engine commands the physical camera.
* [eagleeye CLI](/contracts/cli-command.md) - The command-line surface for starting the app and sending commands to a running engine.
* [Configuration File](/contracts/config-json.md) - The tolerant, atomic JSON settings-and-presets file contract, with an empty dynamics override.
* [Control Socket Protocol](/contracts/control-socket.md) - The one-line JSON protocol over a UNIX socket that all clients use to read state and issue commands.
* [Translation Catalog](/contracts/i18n-catalog.md) - The JSON catalog format, key conventions, placeholder rules and fallback behaviour for translated text.
* [Pose Detector Port](/contracts/pose-detector.md) - The detector interface: frame in, scored boxes with COCO keypoints out, with backend metadata.
* [Session Recording Format](/contracts/session-recording-format.md) - The JSONL session-recording format: time, world-angle measurement, commands, mode and framing.
* [Virtual Camera Output Contract](/contracts/virtual-camera-output.md) - The I420, camera-sized, fixed-rate device-format and slate behaviour contract with conferencing apps.
