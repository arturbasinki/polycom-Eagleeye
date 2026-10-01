"""Sterowanie kamerą Polycom EagleEye IV USB przez V4L2.

Moduły:

* :mod:`eagleeye.v4l2` - dostęp do sprzętu (strumień MJPEG + kontrolki).
* :mod:`eagleeye.detectors` - detekcja twarzy i osób (GPU przez ONNX Runtime).
* :mod:`eagleeye.tracker` - wątek auto-trackingu; logika w ``perception``,
  ``target_filter``, ``head_model``, ``director``, ``actuator``, ``core``.
* :mod:`eagleeye.config` - ustawienia i presety w ``config.json``.
"""

__all__ = ["v4l2", "detectors", "tracker", "config"]
