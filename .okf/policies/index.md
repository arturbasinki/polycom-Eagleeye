# policies

* [Camera Busy Retries](/policies/camera-busy-retry.md) - When the camera is held by another program, the engine names the holder and retries until it is free.
* [Detector Failure Falls Back to CPU](/policies/detector-failure-fallback.md) - Consecutive detector errors switch the pose model from GPU to CPU so tracking keeps working.
* [Manual Zoom Disables Auto-Zoom](/policies/manual-zoom-disables-autozoom.md) - A manual zoom change switches auto-zoom off until explicitly re-enabled.
