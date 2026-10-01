"""Tryb prywatności: plansza dla uczestników, obiektyw w dół, powrót do stanu sprzed.

Kolejność ma znaczenie: plansza pojawia się natychmiast (zanim głowica ruszy),
a przy wyłączaniu najpierw rozkaz powrotu, potem obraz na żywo.
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
        """Pozycja głowicy sprzed włączenia prywatności (None bez kamery)."""
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
        """``resume_tracking=False`` przy zamykaniu aplikacji: głowica wraca,
        ale śledzenie nie rusza (jego rozkazy prędkości przerwałyby powrót)."""
        if not self.active:
            return
        if tracker is not None and self._saved_pose is not None:
            tracker.move_to(pan=self._saved_pose[0], tilt=self._saved_pose[1])
            if self._saved_tracking and resume_tracking:
                tracker.set_enabled(True)
        self.vcam.set_privacy(False)
        self.active = False
