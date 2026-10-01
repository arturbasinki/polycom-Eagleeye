"""Privacy mode: the slate for participants, the lens down, and a return to the previous state.

Order matters: the slate appears immediately (before the head moves), and on disable the
return command goes first, then the live image.
"""

from __future__ import annotations


class Privacy:
    def __init__(self, vcam) -> None:
        self.vcam = vcam
        self.active = False
        self._saved_pose: tuple[float, float] | None = None
        self._saved_tracking = False

    @property
    def saved_pose(self) -> tuple[float, float] | None:
        """Head position from before privacy was enabled (None with no camera)."""
        return self._saved_pose

    def enable(self, tracker) -> None:
        if self.active:
            return
        self.vcam.set_privacy(True)
        self._saved_pose, self._saved_tracking = None, False
        if tracker is not None:
            self._saved_tracking = bool(tracker.enabled)
            if self._saved_tracking:
                tracker.set_enabled(False)
            self._saved_pose = tracker.position()
            tracker.move_to(tilt=tracker.tilt_min())
        self.active = True

    def disable(self, tracker, resume_tracking: bool = True) -> None:
        """``resume_tracking=False`` when the app is closing: the head returns,
        but tracking does not restart (its velocity commands would interrupt the return)."""
        if not self.active:
            return
        if tracker is not None and self._saved_pose is not None:
            tracker.move_to(pan=self._saved_pose[0], tilt=self._saved_pose[1])
            if self._saved_tracking and resume_tracking:
                tracker.set_enabled(True)
        self.vcam.set_privacy(False)
        self.active = False
