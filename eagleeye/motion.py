"""Profile ruchu dla głowicy kamery.

Firmware kamery sam wykonuje każdy ruch absolutny po krzywej S, której profil
prędkości pokrywa się z rozkładem t-Studenta (korelacja +0.92, zmierzone).
Model głowicy (:mod:`eagleeye.head_model`) używa tego kształtu, żeby przewidzieć,
gdzie głowica jest w trakcie ruchu:

* **prędkość** jest proporcjonalna do gęstości ``f(x)`` rozkładu,
* **pozycja** jest jego dystrybuantą (całką z gęstości), więc rośnie monotonicznie
  od 0 do 1, a prędkość na obu końcach dąży do zera.

Rozkład ma jeden parametr - **stopnie swobody ``nu``** - i to on decyduje
o charakterze ruchu:

===================  ==========================================================
``nu = 1``           rozkład Cauchy'ego: **najszerszy, najłagodniejszy**
                     profil - rozkłada przyspieszanie na cały przejazd
``nu = 3`` (domyślne) wyraźny szczyt, wyraźnie cięższe ogony niż Gauss
``nu -> inf``        rozkład normalny: **najostrzejszy szczyt** - kamera długo
                     pełznie, potem szybko przelatuje środek
===================  ==========================================================

Kierunek jest tu wart zapamiętania, bo bywa intuicyjnie odwrotny: **większe
``nu`` daje ostrzejszy szczyt i dłuższe pełzanie na końcach** (zmierzone
szczyt/średnia: 3.53 dla ``nu=1``, 3.89 dla ``nu=20``). Bierze się to stąd, że
w rozkładzie t masa "ucieka" na ogony - a gęstość w zerze maleje (0.318 dla
``nu=1`` wobec 0.399 dla Gaussa). Nie ma tu nieciągłości prędkości, więc nie ma
szarpnięć na starcie ani na końcu - niezależnie od ``nu``.
"""

from __future__ import annotations

import functools
import itertools
import math

# Zakres próbkowania rozkładu w jednostkach "t". Ogony t-Studenta są ciężkie,
# więc dla małych nu masa poza tym przedziałem nie jest zerowa - dlatego
# profil normalizujemy po wzięciu próbek, zamiast liczyć na analityczną jedynkę.
PROFILE_RANGE = 5.0
PROFILE_SAMPLES = 128


def student_t_pdf(x: float, nu: float) -> float:
    """Gęstość rozkładu t-Studenta o ``nu`` stopniach swobody.

    Zaimplementowana z ``math.lgamma``, żeby nie ciągnąć SciPy dla jednej funkcji.
    """
    nu = max(1e-6, float(nu))
    log_coef = math.lgamma((nu + 1.0) / 2.0) - math.lgamma(nu / 2.0) - 0.5 * math.log(nu * math.pi)
    return math.exp(log_coef - ((nu + 1.0) / 2.0) * math.log1p(x * x / nu))


def velocity_shape(nu: float = 3.0, samples: int = PROFILE_SAMPLES) -> list[float]:
    """Kształt prędkości: znormalizowane próbki gęstości t-Studenta (suma = 1)."""
    xs = [-PROFILE_RANGE + 2.0 * PROFILE_RANGE * i / (samples - 1) for i in range(samples)]
    raw = [student_t_pdf(x, nu) for x in xs]
    total = sum(raw)
    return [v / total for v in raw]


def position_shape(nu: float = 3.0, samples: int = PROFILE_SAMPLES) -> list[float]:
    """Kształt pozycji: dystrybuanta profilu prędkości, od 0.0 do 1.0."""
    cumulative = [0.0, *itertools.accumulate(velocity_shape(nu, samples))]
    total = cumulative[-1]
    return [c / total for c in cumulative]


def _interp(table: list[float], fraction: float) -> float:
    """Interpolacja liniowa w tabeli po ułamku postępu 0..1."""
    if fraction <= 0.0:
        return table[0]
    if fraction >= 1.0:
        return table[-1]
    position = fraction * (len(table) - 1)
    index = int(position)
    weight = position - index
    return table[index] * (1.0 - weight) + table[index + 1] * weight


@functools.lru_cache(maxsize=16)
def _position_table(nu: float) -> tuple[float, ...]:
    return tuple(position_shape(nu))


def s_curve(fraction: float, nu: float = 3.0) -> float:
    """Postęp pozycji 0..1 dla ułamka czasu 0..1 - krzywa S firmware'u (profil t-Studenta)."""
    return _interp(_position_table(float(nu)), fraction)  # type: ignore[arg-type]
