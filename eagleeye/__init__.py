"""Control of the Polycom EagleEye IV USB camera over V4L2.

Modules:

* :mod:`eagleeye.v4l2` - hardware access (MJPEG stream + controls).
* :mod:`eagleeye.detectors` - face and person detection (GPU via ONNX).
* :mod:`eagleeye.tracker` - the auto-tracking thread; the logic lives in
  ``perception``, ``target_filter``, ``head_model``,
  ``director``, ``actuator``, ``core``.
* :mod:`eagleeye.config` - settings and presets in ``config.json``.
"""

__all__ = ["v4l2", "detectors", "tracker", "config"]
