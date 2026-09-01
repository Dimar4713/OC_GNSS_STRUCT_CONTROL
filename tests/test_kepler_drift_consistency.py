from __future__ import annotations

from math import degrees, pi, sqrt

import numpy as np
import pytest

from constellation_control.analysis.kepler_drift_consistency import (
    analyze_kepler_drift_consistency,
    kepler_mean_motion_rad_s,
    kepler_period_s,
)
from constellation_control.domain.models import MeanElementDefinition, MeanOrbit

MU = 3.986004418e14


def _orbit(a_m: float) -> MeanOrbit:
    return MeanOrbit(
        a_m=a_m,
        ex=0.001,
        ey=0.0,
        ix=0.1,
        iy=0.0,
        lambda_rad=0.0,
        definition=MeanElementDefinition(
            theory="unit-test-mean",
            force_model_fingerprint="unit-test",
        ),
    )


def test_kepler_period_and_delta_n_match_independent_hand_formula() -> None:
    ref_a = 25_510_000.0
    dep_a = 25_510_001.6
    ref = (_orbit(ref_a),) * 4
    dep = (_orbit(dep_a),) * 4

    ref_period = 2.0 * pi * sqrt(ref_a**3 / MU)
    dep_period = 2.0 * pi * sqrt(dep_a**3 / MU)
    expected_delta_n = 2.0 * pi * (1.0 / dep_period - 1.0 / ref_period)
    expected_deg_day = 360.0 * 86400.0 * (1.0 / dep_period - 1.0 / ref_period)

    diagnostic, delta_n = analyze_kepler_drift_consistency(
        ref,
        dep,
        mu_m3_s2=MU,
        measured_delta_lambda_rate_rad_s=expected_delta_n,
        measured_delta_u_rate_rad_s=expected_delta_n,
    )

    assert kepler_period_s(ref_a, MU) == pytest.approx(ref_period, rel=1e-14)
    assert kepler_mean_motion_rad_s(dep_a, MU) == pytest.approx(2.0 * pi / dep_period, rel=1e-14)
    # Delta T is obtained by subtracting two ~40 ks values; nanosecond-level
    # cancellation is expected in binary float and is irrelevant to the drift check.
    assert diagnostic.initial_period_difference_s == pytest.approx(dep_period - ref_period, abs=1e-9)
    assert diagnostic.initial_kepler_delta_n_rad_s == pytest.approx(expected_delta_n, rel=1e-12)
    assert diagnostic.initial_kepler_delta_n_deg_day == pytest.approx(expected_deg_day, rel=1e-12)
    assert diagnostic.time_mean_kepler_delta_n_deg_day == pytest.approx(expected_deg_day, rel=1e-12)
    assert diagnostic.delta_lambda_minus_kepler_deg_day == pytest.approx(0.0, abs=1e-12)
    assert diagnostic.delta_u_minus_kepler_deg_day == pytest.approx(0.0, abs=1e-12)
    # The vector path uses NumPy sqrt while the hand formula uses scalar math.sqrt.
    # Their last bits need not match for a ~1e-11 rad/s difference; 1e-18 rad/s is
    # far below the engineering scale under test while still catching sign/unit errors.
    assert np.allclose(delta_n, expected_delta_n, rtol=1e-9, atol=1e-18)
    assert expected_delta_n < 0.0


def test_larger_deputy_mean_a_has_longer_period_and_negative_relative_mean_motion() -> None:
    ref_a = 25_510_000.0
    dep_a = ref_a + 10.0
    diagnostic, _ = analyze_kepler_drift_consistency(
        (_orbit(ref_a), _orbit(ref_a)),
        (_orbit(dep_a), _orbit(dep_a)),
        mu_m3_s2=MU,
        measured_delta_lambda_rate_rad_s=0.0,
        measured_delta_u_rate_rad_s=0.0,
    )
    assert diagnostic.initial_period_difference_s > 0.0
    assert diagnostic.initial_kepler_delta_n_rad_s < 0.0
    assert diagnostic.initial_kepler_delta_n_deg_day == pytest.approx(
        degrees(diagnostic.initial_kepler_delta_n_rad_s) * 86400.0,
        rel=1e-15,
    )
