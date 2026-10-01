"""Kompozycja kadru: złoty podział, strona zależna od kierunku twarzy i plan.

Czyste funkcje bez sprzętu. Reżyser pyta je, *gdzie* ma patrzeć kamera; *kiedy*
ruszyć, decyduje sam (histereza, zwłoka).

* Punkt głowy ląduje na górnej linii złotego podziału (y = 0,382 od góry).
* W poziomie: twarz na wprost - środek; twarz zwrócona w bok - punkt po przeciwnej
  stronie, żeby wolne miejsce było przed twarzą (looking room). Strona zmienia się
  dopiero po trwałym odwróceniu głowy, z histerezą (:class:`SideSelector`).
* Plan (CU / MCU / MS) mówi, jaką część wysokości kadru ma zająć odcinek oczy→barki;
  z tego wynika zoom (:func:`zoom_goal`). Wybór planu (:func:`shot_for`) to punkt
  rozszerzenia dla przyszłego "inteligentnego kadrowania".
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .geometry import View, zoom_value_for
from .target_filter import TargetEstimate

GOLDEN = 0.382
# Ułamek wysokości kadru na odcinek oczy→barki. Linia oczu na 0,382, dolna krawędź k takich
# odcinków niżej: 0,382 + k·d = 1. CU k≈1,1 (barki), MCU k≈1,8 (pół klatki), MS k≈3,2 (pas).
# MCU = 0,36: kalibracja 2026-09-25 — przy 0,34 dolna krawędź stawała na splotcie
# słonecznym; +0,02 daje połowę klatki piersiowej.
SHOTS = {"CU": 0.56, "MCU": 0.36, "MS": 0.19}
AUTO_ZOOM_MAX = 4800.0      # powyżej 5000 krzywa zoomu niepewna, a detekcja słabnie
CENTER, LEFT, RIGHT = "środek", "lewy", "prawy"
SIDE_X = {CENTER: 0.5, LEFT: GOLDEN, RIGHT: 1.0 - GOLDEN}


@dataclass(frozen=True)
class Shot:
    name: str
    fraction: float         # część wysokości kadru na odcinek oczy→barki


def shot_for(profile, est: TargetEstimate | None = None) -> Shot:
    """Polityka planu. Dziś: plan z profilu (``profile.shot``). ``est`` - na przyszłość
    (plan dobierany do sytuacji: siedzi / stoi / chodzi)."""
    name = profile.shot if profile.shot in SHOTS else "MCU"
    return Shot(name, SHOTS[name])


def aim(est: TargetEstimate, side: str, view: View) -> tuple[float, float]:
    """Kąty kamery (pan, tilt), przy których głowa ``est`` jest w punkcie strony ``side``.

    Pole widzenia i znaki osi z ``view`` - podaj widok z *docelowym* zoomem, jeśli zoom
    właśnie jedzie. Punkt jest liczony w obrazie, więc odwrócone osie niczego nie zmieniają.
    """
    sp = -1.0 if view.invert_pan else 1.0
    st = -1.0 if view.invert_tilt else 1.0
    return (est.pan - sp * (SIDE_X[side] - 0.5) * view.hfov,
            est.tilt - st * (0.5 - GOLDEN) * view.vfov)


def zoom_goal(est: TargetEstimate, shot: Shot, view: View,
              lo: float = 0.0, hi: float = AUTO_ZOOM_MAX) -> float | None:
    """Wartość zoomu, przy której skala głowy zajmuje ``shot.fraction`` wysokości kadru.

    Skala jest w kątach świata, więc wynik nie zależy od bieżącego zoomu. Bez skali - None.
    """
    if not est.head_scale:
        return None
    wide = replace(view, zoom_value=0.0)
    factor = wide.vfov / (est.head_scale / shot.fraction)
    return min(max(zoom_value_for(factor), lo), hi)


class SideSelector:
    """Strona kadru: środek / lewy / prawy - ze zwłoką i histerezą.

    * środek → bok: ``|yaw| > enter`` nieprzerwanie przez ``dwell`` s,
    * bok → środek: ``|yaw| < exit_`` przez ``dwell`` s,
    * lewy ↔ prawy wprost, po ``dwell`` s trwałego odwrócenia (krótkie obejrzenie się przez
      ramię nie przerzuca kadru; środek tylko po trwałej twarzy na wprost),
    * ``yaw > 0`` (nos na prawo w obrazie) → twarz w LEWYM punkcie - wolne miejsce przed nią,
    * ``yaw is None`` (nosa nie widać) - bez zmian.
    """

    def __init__(self) -> None:
        self.side = CENTER
        self._candidate: str | None = None
        self._since = 0.0

    def reset(self) -> None:
        self.side, self._candidate = CENTER, None

    @property
    def pending(self) -> str | None:
        """Strona, na którą selektor właśnie się namyśla (zwłoka trwa), albo None."""
        return self._candidate

    def update(self, t: float, yaw: float | None, enter: float, exit_: float, dwell: float) -> str:
        if yaw is None:
            self._candidate = None
            return self.side
        wanted = self._wanted(yaw, enter, exit_)
        if wanted == self.side:
            self._candidate = None
            return self.side
        if wanted != self._candidate:
            self._candidate, self._since = wanted, t
        if t - self._since >= dwell:
            self.side, self._candidate = wanted, None
        return self.side

    def _wanted(self, yaw: float, enter: float, exit_: float) -> str:
        facing = LEFT if yaw > 0 else RIGHT
        if self.side == CENTER:
            return facing if abs(yaw) > enter else CENTER
        if abs(yaw) < exit_:
            return CENTER
        if abs(yaw) > enter and facing != self.side:
            # Wprost na przeciwną stronę. Przejście "przez środek" (spec do 2026-09-26)
            # dawało dwa ruchy kamery - na środek i dopiero potem na drugi punkt. Przed
            # obejrzeniem się przez ramię chroni zwłoka: nowa strona musi trwać `dwell`.
            return facing
        return self.side
