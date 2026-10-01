"""Geometria kamery: pole widzenia, skala i przeliczenie piksel <-> kąt świata.

Jednostką kąta są sekundy łuku (arcsec) - te same, w których pracują
kontrolki ``pan_absolute``/``tilt_absolute``. Konwencja zmierzona na tym
egzemplarzu: pan dodatni = w prawo, tilt dodatni = w górę; oś y obrazu rośnie
w dół. "Kąt świata" to kierunek, w którym trzeba by ustawić kamerę, żeby dany
punkt znalazł się na środku kadru - nie zmienia się, gdy kamera się obraca.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

ARCSEC_PER_DEG = 3600.0
HFOV_WIDE_ARCSEC = 204.0 * 1280.0   # ~72.5° przy zoomie 1x (zmierzone)
ZOOM_MAX_VALUE = 5680
ZOOM_MAX_FACTOR = 12.0


def deg(value: float) -> float:
    """Stopnie -> arcsec."""
    return value * ARCSEC_PER_DEG


# Krotność przybliżenia zmierzona na tym egzemplarzu (2026-09-24, 1920x1080): klatkę z danym
# zoomem zmniejszano i dopasowywano do klatki bez zoomu; w dwóch punktach potwierdzone ruchem pan
# o znany kąt (800: 58.2°, 2400: 37.2°). Krzywa jest mniej więcej wykładnicza - model liniowy
# zawyżał przybliżenie 2-3 razy (przy 2400: 5.65x zamiast 1.99x) i śledzenie dojeżdżało „na raty”.
# Powyżej 5000 dopasowanie jest niepewne (wzorzec za mały): 5600 z pierwszego przebiegu, 5680 = 12x
# z danych producenta.
ZOOM_CURVE = (
    (0, 1.0), (400, 1.122), (800, 1.233), (1200, 1.380), (1600, 1.551), (2000, 1.734),
    (2400, 1.985), (2800, 2.287), (3200, 2.674), (3600, 3.140), (4000, 3.804), (4200, 4.189),
    (4400, 4.617), (4600, 5.109), (4800, 5.686), (5000, 6.429), (5600, 10.323),
    (ZOOM_MAX_VALUE, ZOOM_MAX_FACTOR),
)


def zoom_factor(zoom_value: float) -> float:
    """Wartość kontrolki zoomu -> krotność przybliżenia, z krzywej zmierzonej (ZOOM_CURVE).

    Między punktami interpolujemy logarytm krotności - krzywa jest bliska wykładniczej.
    """
    z = min(max(float(zoom_value), 0.0), float(ZOOM_MAX_VALUE))
    for (z0, f0), (z1, f1) in zip(ZOOM_CURVE, ZOOM_CURVE[1:]):
        if z <= z1:
            a = (z - z0) / (z1 - z0)
            return math.exp(math.log(f0) + a * (math.log(f1) - math.log(f0)))
    return ZOOM_MAX_FACTOR


def zoom_value_for(factor: float) -> float:
    """Krotność przybliżenia -> wartość kontrolki zoomu (odwrotność :func:`zoom_factor`).

    Te same punkty ``ZOOM_CURVE`` i ta sama interpolacja logarytmu krotności.
    Poza zakresem przycina do [0, ZOOM_MAX_VALUE].
    """
    f = min(max(float(factor), 1.0), ZOOM_MAX_FACTOR)
    for (z0, f0), (z1, f1) in zip(ZOOM_CURVE, ZOOM_CURVE[1:]):
        if f <= f1:
            a = (math.log(f) - math.log(f0)) / (math.log(f1) - math.log(f0))
            return z0 + a * (z1 - z0)
    return float(ZOOM_MAX_VALUE)


@dataclass(frozen=True)
class View:
    """Pole widzenia klatki o danym rozmiarze przy danym zoomie."""

    frame_w: int
    frame_h: int
    zoom_value: float = 0.0
    invert_pan: bool = False
    invert_tilt: bool = False

    @property
    def hfov(self) -> float:
        return HFOV_WIDE_ARCSEC / zoom_factor(self.zoom_value)

    @property
    def vfov(self) -> float:
        return self.hfov * self.frame_h / self.frame_w

    @property
    def arcsec_per_px(self) -> float:
        return self.hfov / self.frame_w

    def _signs(self) -> tuple[float, float]:
        return (-1.0 if self.invert_pan else 1.0, -1.0 if self.invert_tilt else 1.0)

    def pixel_to_world(self, x: float, y: float, cam_pan: float, cam_tilt: float) -> tuple[float, float]:
        sp, st = self._signs()
        s = self.arcsec_per_px
        return (cam_pan + sp * (x - self.frame_w / 2.0) * s,
                cam_tilt - st * (y - self.frame_h / 2.0) * s)

    def world_to_pixel(self, pan: float, tilt: float, cam_pan: float, cam_tilt: float) -> tuple[float, float]:
        sp, st = self._signs()
        s = self.arcsec_per_px
        return (self.frame_w / 2.0 + sp * (pan - cam_pan) / s,
                self.frame_h / 2.0 - st * (tilt - cam_tilt) / s)
