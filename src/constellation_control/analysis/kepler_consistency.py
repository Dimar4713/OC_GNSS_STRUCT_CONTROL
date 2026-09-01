from __future__ import annotations

from dataclasses import dataclass
from math import pi, sqrt

import numpy as np


DAY_S = 86400.0


@dataclass(frozen=True)
class KeplerRelativeDriftBaseline:
    reference_a_mean_m: np.ndarray
    deputy_a_mean_m: np.ndarray
    reference_period_s: np.ndarray
    deputy_period_s: np.ndarray
    period_difference_s: np.ndarray
    reference_mean_motion_rad_s: np.ndarray
    deputy_mean_motion_rad_s: np.ndarray
    delta_n_rad_s: np.ndarray
    reference_initial_a_mean_m: float
    deputy_initial_a_mean_m: float
    reference_time_mean_a_mean_m: float
    deputy_time_mean_a_mean_m: float
    reference_initial_period_s: float
    deputy_initial_period_s: float
    initial_period_difference_s: float
    reference_period_at_time_mean_a_s: float
    deputy_period_at_time_mean_a_s: float
    period_difference_at_time_mean_a_s: float
    initial_delta_n_rad_s: float
    initial_delta_n_deg_day: float
    time_mean_delta_n_rad_s: float
    time_mean_delta_n_deg_day: float


def angular_rate_deg_day(rate_rad_s: float) -> float:
    return float(np.degrees(float(rate_rad_s)) * DAY_S)


def _validate_history(times_s: np.ndarray, values: np.ndarray, name: str) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    if values.ndim != 1 or values.shape != times_s.shape or values.size == 0:
        raise ValueError(f"{name} must be a non-empty one-dimensional history matching times_s")
    if not np.all(np.isfinite(values)) or np.any(values <= 0.0):
        raise ValueError(f"{name} must contain finite positive mean semi-major axes")
    return values


def _time_mean(times_s: np.ndarray, values: np.ndarray) -> float:
    if values.size == 1:
        return float(values[0])
    dt = np.diff(times_s)
    integral = float(np.sum(0.5 * (values[:-1] + values[1:]) * dt))
    return integral / float(times_s[-1] - times_s[0])


def _mean_motion_rad_s(a_m: np.ndarray | float, mu_m3_s2: float) -> np.ndarray:
    a = np.asarray(a_m, dtype=float)
    return np.sqrt(float(mu_m3_s2) / np.power(a, 3))


def _period_s(a_m: np.ndarray | float, mu_m3_s2: float) -> np.ndarray:
    return 2.0 * pi / _mean_motion_rad_s(a_m, mu_m3_s2)


def kepler_relative_drift_baseline(
    times_s: np.ndarray,
    reference_a_mean_m: np.ndarray,
    deputy_a_mean_m: np.ndarray,
    mu_m3_s2: float,
) -> KeplerRelativeDriftBaseline:
    """Build an independent central-field relative drift baseline from mean ``a`` histories.

    The returned ``Delta n`` is deputy minus reference.  It is a Kepler central-field
    consistency diagnostic only; it is not an expectation that a full-force mean
    ``Delta lambda`` or ``Delta u`` secular rate must be identical.
    """

    times = np.asarray(times_s, dtype=float)
    if times.ndim != 1 or times.size == 0 or not np.all(np.isfinite(times)):
        raise ValueError("times_s must be a non-empty finite one-dimensional history")
    if times.size > 1 and np.any(np.diff(times) <= 0.0):
        raise ValueError("times_s must be strictly increasing")
    mu = float(mu_m3_s2)
    if not np.isfinite(mu) or mu <= 0.0:
        raise ValueError("mu_m3_s2 must be finite and positive")

    reference_a = _validate_history(times, reference_a_mean_m, "reference_a_mean_m")
    deputy_a = _validate_history(times, deputy_a_mean_m, "deputy_a_mean_m")
    reference_n = _mean_motion_rad_s(reference_a, mu)
    deputy_n = _mean_motion_rad_s(deputy_a, mu)
    delta_n = deputy_n - reference_n
    reference_period = _period_s(reference_a, mu)
    deputy_period = _period_s(deputy_a, mu)
    period_difference = deputy_period - reference_period

    reference_time_mean_a = _time_mean(times, reference_a)
    deputy_time_mean_a = _time_mean(times, deputy_a)
    reference_period_at_time_mean_a = float(_period_s(reference_time_mean_a, mu))
    deputy_period_at_time_mean_a = float(_period_s(deputy_time_mean_a, mu))
    initial_delta_n = float(delta_n[0])
    time_mean_delta_n = _time_mean(times, delta_n)

    return KeplerRelativeDriftBaseline(
        reference_a_mean_m=reference_a,
        deputy_a_mean_m=deputy_a,
        reference_period_s=reference_period,
        deputy_period_s=deputy_period,
        period_difference_s=period_difference,
        reference_mean_motion_rad_s=reference_n,
        deputy_mean_motion_rad_s=deputy_n,
        delta_n_rad_s=delta_n,
        reference_initial_a_mean_m=float(reference_a[0]),
        deputy_initial_a_mean_m=float(deputy_a[0]),
        reference_time_mean_a_mean_m=reference_time_mean_a,
        deputy_time_mean_a_mean_m=deputy_time_mean_a,
        reference_initial_period_s=float(reference_period[0]),
        deputy_initial_period_s=float(deputy_period[0]),
        initial_period_difference_s=float(period_difference[0]),
        reference_period_at_time_mean_a_s=reference_period_at_time_mean_a,
        deputy_period_at_time_mean_a_s=deputy_period_at_time_mean_a,
        period_difference_at_time_mean_a_s=(
            deputy_period_at_time_mean_a - reference_period_at_time_mean_a
        ),
        initial_delta_n_rad_s=initial_delta_n,
        initial_delta_n_deg_day=angular_rate_deg_day(initial_delta_n),
        time_mean_delta_n_rad_s=time_mean_delta_n,
        time_mean_delta_n_deg_day=angular_rate_deg_day(time_mean_delta_n),
    )
