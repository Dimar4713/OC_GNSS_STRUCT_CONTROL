from __future__ import annotations

from dataclasses import dataclass
from math import cos, sqrt

from constellation_control.dynamics.orbits import ClassicalElements
from constellation_control.domain.models import ForceModelConfig


@dataclass(frozen=True)
class SecularRates:
    raan_rad_s: float
    argp_rad_s: float
    mean_anomaly_rad_s: float


def mean_motion(a_m: float, mu_m3_s2: float) -> float:
    return sqrt(mu_m3_s2 / a_m**3)


def first_order_j2_rates(elements: ClassicalElements, force: ForceModelConfig) -> SecularRates:
    n = mean_motion(elements.a_m, force.mu_m3_s2)
    if force.j2 == 0.0:
        return SecularRates(0.0, 0.0, n)
    p = elements.a_m * (1.0 - elements.e**2)
    factor = force.j2 * n * (force.reference_radius_m / p) ** 2
    c = cos(elements.i_rad)
    raan_dot = -1.5 * factor * c
    argp_dot = 0.75 * factor * (5.0 * c * c - 1.0)
    mean_dot = n + 0.75 * factor * sqrt(1.0 - elements.e**2) * (3.0 * c * c - 1.0)
    return SecularRates(raan_dot, argp_dot, mean_dot)
