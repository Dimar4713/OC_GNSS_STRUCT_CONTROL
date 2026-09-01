from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import degrees, pi, sqrt

import numpy as np

from constellation_control.domain.models import MeanOrbit

DAY_S = 86400.0


@dataclass(frozen=True)
class KeplerDriftConsistency:
    reference_initial_a_mean_m: float
    deputy_initial_a_mean_m: float
    reference_time_mean_a_mean_m: float
    deputy_time_mean_a_mean_m: float
    reference_initial_kepler_period_s: float
    deputy_initial_kepler_period_s: float
    initial_period_difference_s: float
    reference_time_mean_kepler_period_s: float
    deputy_time_mean_kepler_period_s: float
    time_mean_period_difference_s: float
    initial_kepler_delta_n_rad_s: float
    initial_kepler_delta_n_deg_day: float
    time_mean_kepler_delta_n_rad_s: float
    time_mean_kepler_delta_n_deg_day: float
    measured_delta_lambda_rate_rad_s: float
    measured_delta_lambda_rate_deg_day: float
    measured_delta_u_rate_rad_s: float
    measured_delta_u_rate_deg_day: float
    delta_lambda_minus_kepler_rad_s: float
    delta_lambda_minus_kepler_deg_day: float
    delta_u_minus_kepler_rad_s: float
    delta_u_minus_kepler_deg_day: float
    semantics: str


def kepler_mean_motion_rad_s(a_mean_m: float, mu_m3_s2: float) -> float:
    a = float(a_mean_m)
    mu = float(mu_m3_s2)
    if not np.isfinite(a) or a <= 0.0:
        raise ValueError("mean semi-major axis must be finite and positive")
    if not np.isfinite(mu) or mu <= 0.0:
        raise ValueError("central-body mu must be finite and positive")
    return sqrt(mu / (a**3))


def kepler_period_s(a_mean_m: float, mu_m3_s2: float) -> float:
    return 2.0 * pi / kepler_mean_motion_rad_s(a_mean_m, mu_m3_s2)


def analyze_kepler_drift_consistency(
    reference: Sequence[MeanOrbit],
    deputy: Sequence[MeanOrbit],
    *,
    mu_m3_s2: float,
    measured_delta_lambda_rate_rad_s: float,
    measured_delta_u_rate_rad_s: float,
) -> tuple[KeplerDriftConsistency, np.ndarray]:
    if len(reference) != len(deputy) or not reference:
        raise ValueError("reference and deputy mean histories must be non-empty and have equal length")

    ref_a = np.asarray([item.a_m for item in reference], dtype=float)
    dep_a = np.asarray([item.a_m for item in deputy], dtype=float)
    if not np.all(np.isfinite(ref_a)) or not np.all(np.isfinite(dep_a)):
        raise ValueError("mean semi-major-axis histories must be finite")
    if np.any(ref_a <= 0.0) or np.any(dep_a <= 0.0):
        raise ValueError("mean semi-major-axis histories must be positive")

    mu = float(mu_m3_s2)
    if not np.isfinite(mu) or mu <= 0.0:
        raise ValueError("central-body mu must be finite and positive")

    delta_n = np.sqrt(mu / dep_a**3) - np.sqrt(mu / ref_a**3)
    initial_delta_n = float(delta_n[0])
    time_mean_delta_n = float(np.mean(delta_n))

    ref_initial_period = kepler_period_s(float(ref_a[0]), mu)
    dep_initial_period = kepler_period_s(float(dep_a[0]), mu)
    ref_mean_a = float(np.mean(ref_a))
    dep_mean_a = float(np.mean(dep_a))
    ref_mean_period = kepler_period_s(ref_mean_a, mu)
    dep_mean_period = kepler_period_s(dep_mean_a, mu)

    measured_lambda = float(measured_delta_lambda_rate_rad_s)
    measured_u = float(measured_delta_u_rate_rad_s)
    for value, name in (
        (measured_lambda, "measured Delta lambda rate"),
        (measured_u, "measured Delta u rate"),
    ):
        if not np.isfinite(value):
            raise ValueError(f"{name} must be finite")

    def deg_day(rate_rad_s: float) -> float:
        return degrees(rate_rad_s) * DAY_S

    lambda_residual = measured_lambda - time_mean_delta_n
    u_residual = measured_u - time_mean_delta_n
    diagnostic = KeplerDriftConsistency(
        reference_initial_a_mean_m=float(ref_a[0]),
        deputy_initial_a_mean_m=float(dep_a[0]),
        reference_time_mean_a_mean_m=ref_mean_a,
        deputy_time_mean_a_mean_m=dep_mean_a,
        reference_initial_kepler_period_s=ref_initial_period,
        deputy_initial_kepler_period_s=dep_initial_period,
        initial_period_difference_s=dep_initial_period - ref_initial_period,
        reference_time_mean_kepler_period_s=ref_mean_period,
        deputy_time_mean_kepler_period_s=dep_mean_period,
        time_mean_period_difference_s=dep_mean_period - ref_mean_period,
        initial_kepler_delta_n_rad_s=initial_delta_n,
        initial_kepler_delta_n_deg_day=deg_day(initial_delta_n),
        time_mean_kepler_delta_n_rad_s=time_mean_delta_n,
        time_mean_kepler_delta_n_deg_day=deg_day(time_mean_delta_n),
        measured_delta_lambda_rate_rad_s=measured_lambda,
        measured_delta_lambda_rate_deg_day=deg_day(measured_lambda),
        measured_delta_u_rate_rad_s=measured_u,
        measured_delta_u_rate_deg_day=deg_day(measured_u),
        delta_lambda_minus_kepler_rad_s=lambda_residual,
        delta_lambda_minus_kepler_deg_day=deg_day(lambda_residual),
        delta_u_minus_kepler_rad_s=u_residual,
        delta_u_minus_kepler_deg_day=deg_day(u_residual),
        semantics=(
            "Kepler Delta n is an independent central-field baseline derived only from force-model-consistent "
            "mean semi-major axes and scenario mu. Full-force measured Delta lambda and Delta u=lambda-Omega "
            "may differ because of nodal/perigee dynamics and non-Kepler perturbations."
        ),
    )
    return diagnostic, delta_n
