#!/usr/bin/env python3
"""Motion profile tests: Student's t shape, monotonicity, smoothness.

Running::

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
    """The Student's t density is symmetric and positive."""
    for nu in (1.0, 3.0, 30.0):
        values = [student_t_pdf((i - 100) / 20.0, nu) for i in range(201)]
        assert all(v > 0 for v in values), f"the density must be positive (nu={nu})"
        assert abs(values[100] - max(values)) < 1e-9, "the peak should be at zero"
        assert abs(values[90] - values[110]) < 1e-12, f"no symmetry (nu={nu})"
    print("    density: symmetric, positive, peak at zero")


def test_pdf_matches_known_values() -> None:
    """Reference values for the Student's t distribution (checking the formula)."""
    # For nu=1 (Cauchy): f(0) = 1/pi
    assert abs(student_t_pdf(0.0, 1.0) - 1.0 / math.pi) < 1e-9
    # For large nu it converges to the normal distribution: f(0) = 1/sqrt(2*pi)
    assert abs(student_t_pdf(0.0, 1e7) - 1.0 / math.sqrt(2 * math.pi)) < 1e-4
    print(f"    f(0) for nu=1: {student_t_pdf(0.0, 1.0):.6f} (1/pi = {1/math.pi:.6f})")
    print(f"    f(0) for large nu: {student_t_pdf(0.0, 1e7):.6f} "
          f"(1/sqrt(2pi) = {1/math.sqrt(2*math.pi):.6f})")


def test_velocity_shape_sums_to_one() -> None:
    for nu in (1.0, 3.0, 12.0):
        total = sum(velocity_shape(nu))
        assert abs(total - 1.0) < 1e-9, f"the velocity profile must sum to 1 (nu={nu})"
    print("    the velocity profile sums to 1 for every nu")


def test_velocity_shape_is_bell_shaped() -> None:
    """Velocity rises toward the middle and falls at the ends - that is the 'bell'."""
    for nu in (1.0, 3.0, 12.0):
        v = velocity_shape(nu, 128)
        peak = v.index(max(v))
        assert 55 <= peak <= 72, f"the peak should land in the middle, it is at {peak}/127"
        assert v[0] < max(v) * 0.05, "the start should be slow"
        assert v[-1] < max(v) * 0.05, "the end should be slow"
        half = [i for i, x in enumerate(v) if x > max(v) / 2]
        assert half == list(range(min(half), max(half) + 1)), "the profile must be unimodal"
    print("    profile unimodal, peak in the middle, slow start and end")


def test_heavier_tails_for_smaller_nu() -> None:
    """Smaller nu => heavier tails (a longer gentle acceleration)."""
    ratios = {}
    for nu in (1.0, 3.0, 30.0):
        v = velocity_shape(nu, 128)
        ratios[nu] = v[5] / max(v)
    print(f"    relative velocity at the start: " +
          ", ".join(f"nu={k:g}: {v:.4f}" for k, v in ratios.items()))
    assert ratios[1.0] > ratios[3.0] > ratios[30.0], "smaller nu must have a heavier tail"


def test_converges_to_gaussian_for_large_nu() -> None:
    """For large nu the profile converges to the normal distribution."""
    def gaussian(n: int = 128) -> list[float]:
        xs = [-5.0 + 10.0 * i / (n - 1) for i in range(n)]
        raw = [math.exp(-x * x / 2.0) for x in xs]
        total = sum(raw)
        return [r / total for r in raw]

    g = gaussian()
    distance = {nu: sum(abs(a - b) for a, b in zip(g, velocity_shape(nu, 128)))
                for nu in (1.0, 3.0, 100.0)}
    print("    distance from Gaussian: " + ", ".join(f"nu={k:g}: {v:.4f}"
                                                  for k, v in distance.items()))
    assert distance[100.0] < 0.01, "large nu should give practically a Gaussian"
    assert distance[1.0] > distance[3.0] > distance[100.0], "decreasing convergence"


def test_position_shape_is_monotonic_from_zero_to_one() -> None:
    for nu in (1.0, 3.0, 30.0):
        p = position_shape(nu, 128)
        assert abs(p[0]) < 1e-12, "position starts at 0"
        assert abs(p[-1] - 1.0) < 1e-12, "position ends at 1"
        assert all(b >= a - 1e-12 for a, b in zip(p, p[1:])), f"position must increase (nu={nu})"
    print("    position: 0 -> 1, monotonic for every nu")


def test_larger_nu_gives_sharper_peak() -> None:
    """Changing nu really changes the shape - and in the direction opposite to intuition.

    Measured: larger nu => a sharper peak (a longer crawl at the ends,
    a faster run through the middle), because in the t distribution the mass escapes
    to the tails and the density at zero falls. Smaller nu => a wider, gentler profile.
    """
    crest = {}
    for nu in (1.0, 20.0):
        vel = velocity_shape(nu)
        crest[nu] = max(vel) / (sum(vel) / len(vel))
    print(f"    peak/mean: nu=1 -> {crest[1.0]:.2f}, nu=20 -> {crest[20.0]:.2f}")
    assert crest[20.0] > crest[1.0], "larger nu should give a sharper peak"


def test_s_curve_starts_and_ends_slowly() -> None:
    """The firmware's S-curve: a gentle start and arrival, with no velocity jump at the ends."""
    start = s_curve(0.05) - s_curve(0.0)
    middle = s_curve(0.55) - s_curve(0.5)
    end = s_curve(1.0) - s_curve(0.95)
    assert start < middle / 3 and end < middle / 3


if __name__ == "__main__":
    run(globals(), "Motion profile")
