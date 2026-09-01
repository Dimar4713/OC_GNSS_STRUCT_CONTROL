import math

import numpy as np
import pytest

from constellation_control.analysis.kepler_consistency import (
    DAY_S,
    kepler_relative_drift_baseline,
)


def _n(a_m: float, mu_m3_s2: float) -> float:
    return math.sqrt(mu_m3_s2 / a_m**3)


def test_kepler_baseline_reconstructs_known_two_orbit_drift_sign_and_units() -> None:
    mu = 3.986004418e14
    reference_a = 25_510_000.0
    deputy_a = 25_511_000.0
    times = np.array([0.0, 900.0, 1800.0])

    result = kepler_relative_drift_baseline(
        times,
        np.full(times.shape, reference_a),
        np.full(times.shape, deputy_a),
        mu,
    )

    expected_delta_n = _n(deputy_a, mu) - _n(reference_a, mu)
    expected_deg_day = math.degrees(expected_delta_n) * DAY_S
    expected_period_difference = 2.0 * math.pi / _n(deputy_a, mu) - 2.0 * math.pi / _n(
        reference_a, mu
    )

    assert expected_delta_n < 0.0
    assert result.initial_delta_n_rad_s == pytest.approx(expected_delta_n, rel=1e-13)
    assert result.time_mean_delta_n_rad_s == pytest.approx(expected_delta_n, rel=1e-13)
    assert result.initial_delta_n_deg_day == pytest.approx(expected_deg_day, rel=1e-13)
    assert result.time_mean_delta_n_deg_day == pytest.approx(expected_deg_day, rel=1e-13)
    assert result.initial_period_difference_s == pytest.approx(expected_period_difference, rel=1e-13)
    assert result.period_difference_at_time_mean_a_s == pytest.approx(
        expected_period_difference, rel=1e-13
    )


def test_kepler_baseline_uses_time_weighted_mean_for_nonuniform_history() -> None:
    mu = 3.986004418e14
    times = np.array([0.0, 10.0, 40.0])
    reference = np.array([25_510_000.0, 25_510_100.0, 25_510_300.0])
    deputy = np.array([25_511_000.0, 25_511_100.0, 25_511_500.0])

    result = kepler_relative_drift_baseline(times, reference, deputy, mu)

    dt = np.diff(times)
    expected_reference_mean = float(
        np.sum(0.5 * (reference[:-1] + reference[1:]) * dt) / (times[-1] - times[0])
    )
    delta_n = np.array([_n(a, mu) for a in deputy]) - np.array([_n(a, mu) for a in reference])
    expected_delta_n_mean = float(
        np.sum(0.5 * (delta_n[:-1] + delta_n[1:]) * dt) / (times[-1] - times[0])
    )

    assert result.reference_time_mean_a_mean_m == pytest.approx(expected_reference_mean)
    assert result.time_mean_delta_n_rad_s == pytest.approx(expected_delta_n_mean, rel=1e-13)


def test_kepler_baseline_rejects_osculating_like_invalid_or_misaligned_inputs() -> None:
    times = np.array([0.0, 10.0])
    with pytest.raises(ValueError, match="matching times_s"):
        kepler_relative_drift_baseline(times, np.array([25_510_000.0]), np.array([25_511_000.0]), 3.986e14)
    with pytest.raises(ValueError, match="positive mean semi-major axes"):
        kepler_relative_drift_baseline(times, np.array([25_510_000.0, -1.0]), np.array([25_511_000.0, 25_511_000.0]), 3.986e14)
