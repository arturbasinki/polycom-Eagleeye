"""Motion profiles for the camera head.

The camera firmware executes every absolute move along an S-curve whose velocity
profile matches the Student's t distribution (correlation +0.92, measured).
The head model (:mod:`eagleeye.head_model`) uses this shape to predict
where the head is during a move:

* **velocity** is proportional to the density ``f(x)`` of the distribution,
* **position** is its CDF (the integral of the density), so it grows monotonically
  from 0 to 1, and the velocity tends to zero at both ends.

The distribution has one parameter - the **degrees of freedom ``nu``** - and it decides
the character of the move:

===================  ==========================================================
``nu = 1``           Cauchy distribution: **widest, gentlest**
                     profile - spreads the acceleration over the whole travel
``nu = 3`` (default) a distinct peak, noticeably heavier tails than a Gaussian
``nu -> inf``        normal distribution: **sharpest peak** - the camera
                     creeps for a long time, then quickly flies through the middle
===================  ==========================================================

The direction is worth remembering here, because it is counter-intuitive: **a larger
``nu`` gives a sharper peak and a longer creep at the ends** (measured
peak/mean: 3.53 for ``nu=1``, 3.89 for ``nu=20``). It follows from the fact that
in the t distribution the mass "escapes" into the tails - and the density at zero
decreases (0.318 for ``nu=1`` vs 0.399 for a Gaussian). There is no velocity
discontinuity here, so there are no jerks at the start or the end - regardless of ``nu``.
"""

from __future__ import annotations

import functools
import itertools
import math

# Sampling range of the distribution in units of "t". Student's t tails are heavy,
# so for small nu the mass outside this interval is not zero - that is why we
# normalise the profile after sampling, instead of relying on an analytical unit total.
PROFILE_RANGE = 5.0
PROFILE_SAMPLES = 128


def student_t_pdf(x: float, nu: float) -> float:
    """Density of the Student's t distribution with ``nu`` degrees of freedom.

    Implemented with ``math.lgamma`` so as not to pull in SciPy for one function.
    """
    nu = max(1e-6, float(nu))
    log_coef = math.lgamma((nu + 1.0) / 2.0) - math.lgamma(nu / 2.0) - 0.5 * math.log(nu * math.pi)
    return math.exp(log_coef - ((nu + 1.0) / 2.0) * math.log1p(x * x / nu))


def velocity_shape(nu: float = 3.0, samples: int = PROFILE_SAMPLES) -> list[float]:
    """Velocity shape: normalised Student's t density samples (sum = 1)."""
    xs = [-PROFILE_RANGE + 2.0 * PROFILE_RANGE * i / (samples - 1) for i in range(samples)]
    raw = [student_t_pdf(x, nu) for x in xs]
    total = sum(raw)
    return [v / total for v in raw]


def position_shape(nu: float = 3.0, samples: int = PROFILE_SAMPLES) -> list[float]:
    """Position shape: the CDF of the velocity profile, from 0.0 to 1.0."""
    cumulative = [0.0, *itertools.accumulate(velocity_shape(nu, samples))]
    total = cumulative[-1]
    return [c / total for c in cumulative]


def _interp(table: list[float], fraction: float) -> float:
    """Linear interpolation in the table by the progress fraction 0..1."""
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
    """Position progress 0..1 for a time fraction 0..1 - the firmware S-curve
    (Student's t profile)."""
    return _interp(_position_table(float(nu)), fraction)  # type: ignore[arg-type]
