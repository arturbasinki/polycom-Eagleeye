#!/usr/bin/env python3
"""Testy profilu ruchu: kształt t-Studenta, monotoniczność, płynność.

Uruchomienie::

    .venv/bin/python tests/test_motion.py
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from runner import run  # noqa: E402

from eagleeye.motion import position_shape, s_curve, student_t_pdf, velocity_shape  # noqa: E402


def test_pdf_is_symmetric_and_positive() -> None:
    """Gęstość t-Studenta jest symetryczna i dodatnia."""
    for nu in (1.0, 3.0, 30.0):
        values = [student_t_pdf((i - 100) / 20.0, nu) for i in range(201)]
        assert all(v > 0 for v in values), f"gęstość musi być dodatnia (nu={nu})"
        assert abs(values[100] - max(values)) < 1e-9, "szczyt powinien być w zerze"
        assert abs(values[90] - values[110]) < 1e-12, f"brak symetrii (nu={nu})"
    print("    gęstość: symetryczna, dodatnia, szczyt w zerze")


def test_pdf_matches_known_values() -> None:
    """Wartości odniesienia dla rozkładu t-Studenta (sprawdzenie wzoru)."""
    # Dla nu=1 (Cauchy): f(0) = 1/pi
    assert abs(student_t_pdf(0.0, 1.0) - 1.0 / math.pi) < 1e-9
    # Dla duzego nu zbiega do rozkładu normalnego: f(0) = 1/sqrt(2*pi)
    assert abs(student_t_pdf(0.0, 1e7) - 1.0 / math.sqrt(2 * math.pi)) < 1e-4
    print(f"    f(0) dla nu=1: {student_t_pdf(0.0, 1.0):.6f} (1/pi = {1/math.pi:.6f})")
    print(f"    f(0) dla dużego nu: {student_t_pdf(0.0, 1e7):.6f} "
          f"(1/sqrt(2pi) = {1/math.sqrt(2*math.pi):.6f})")


def test_velocity_shape_sums_to_one() -> None:
    for nu in (1.0, 3.0, 12.0):
        total = sum(velocity_shape(nu))
        assert abs(total - 1.0) < 1e-9, f"profil prędkości musi sumować się do 1 (nu={nu})"
    print("    profil prędkości sumuje się do 1 dla każdego nu")


def test_velocity_shape_is_bell_shaped() -> None:
    """Prędkość rośnie do środka i maleje na końcach - to jest ten 'dzwon'."""
    for nu in (1.0, 3.0, 12.0):
        v = velocity_shape(nu, 128)
        peak = v.index(max(v))
        assert 55 <= peak <= 72, f"szczyt powinien wypaść w środku, jest na {peak}/127"
        assert v[0] < max(v) * 0.05, "start powinien być wolny"
        assert v[-1] < max(v) * 0.05, "koniec powinien być wolny"
        half = [i for i, x in enumerate(v) if x > max(v) / 2]
        assert half == list(range(min(half), max(half) + 1)), "profil musi być jednomodalny"
    print("    profil jednomodalny, szczyt w środku, wolny start i koniec")


def test_heavier_tails_for_smaller_nu() -> None:
    """Mniejsze nu => cięższe ogony (dłuższe łagodne rozpędzanie)."""
    ratios = {}
    for nu in (1.0, 3.0, 30.0):
        v = velocity_shape(nu, 128)
        ratios[nu] = v[5] / max(v)
    print(f"    względna prędkość przy starcie: " +
          ", ".join(f"nu={k:g}: {v:.4f}" for k, v in ratios.items()))
    assert ratios[1.0] > ratios[3.0] > ratios[30.0], "mniejsze nu musi mieć cięższy ogon"


def test_converges_to_gaussian_for_large_nu() -> None:
    """Przy dużym nu profil zbiega do rozkładu normalnego."""
    def gaussian(n: int = 128) -> list[float]:
        xs = [-5.0 + 10.0 * i / (n - 1) for i in range(n)]
        raw = [math.exp(-x * x / 2.0) for x in xs]
        total = sum(raw)
        return [r / total for r in raw]

    g = gaussian()
    distance = {nu: sum(abs(a - b) for a, b in zip(g, velocity_shape(nu, 128)))
                for nu in (1.0, 3.0, 100.0)}
    print("    odległość od Gaussa: " + ", ".join(f"nu={k:g}: {v:.4f}"
                                                  for k, v in distance.items()))
    assert distance[100.0] < 0.01, "duże nu powinno dawać praktycznie Gaussa"
    assert distance[1.0] > distance[3.0] > distance[100.0], "malejąca zbieżność"


def test_position_shape_is_monotonic_from_zero_to_one() -> None:
    for nu in (1.0, 3.0, 30.0):
        p = position_shape(nu, 128)
        assert abs(p[0]) < 1e-12, "pozycja startuje od 0"
        assert abs(p[-1] - 1.0) < 1e-12, "pozycja kończy na 1"
        assert all(b >= a - 1e-12 for a, b in zip(p, p[1:])), f"pozycja musi rosnąć (nu={nu})"
    print("    pozycja: 0 -> 1, monotoniczna dla każdego nu")


def test_larger_nu_gives_sharper_peak() -> None:
    """Zmiana nu realnie zmienia przebieg - i to w stronę odwrotną niż intuicja.

    Zmierzone: większe nu => ostrzejszy szczyt (dłuższe pełzanie na końcach,
    szybszy przelot środkiem), bo w rozkładzie t masa ucieka na ogony i gęstość
    w zerze maleje. Mniejsze nu => szerszy, łagodniejszy profil.
    """
    crest = {}
    for nu in (1.0, 20.0):
        vel = velocity_shape(nu)
        crest[nu] = max(vel) / (sum(vel) / len(vel))
    print(f"    szczyt/średnia: nu=1 -> {crest[1.0]:.2f}, nu=20 -> {crest[20.0]:.2f}")
    assert crest[20.0] > crest[1.0], "większe nu powinno dawać ostrzejszy szczyt"


def test_s_curve_starts_and_ends_slowly() -> None:
    """Krzywa S firmware'u: łagodny start i dojazd, bez skoku prędkości na końcach."""
    start = s_curve(0.05) - s_curve(0.0)
    middle = s_curve(0.55) - s_curve(0.5)
    end = s_curve(1.0) - s_curve(0.95)
    assert start < middle / 3 and end < middle / 3


if __name__ == "__main__":
    run(globals(), "Profil ruchu")
