import math

import numpy as np
import pytest

from constellation_control.analysis.drift import SIDEREAL_YEAR_S, harmonic_regression


def test_harmonic_regression_reports_component_period_amplitude_and_peak_to_peak() -> None:
    period_s = 1200.0
    amplitude_rad = 0.2
    frequency = 2.0 * math.pi / period_s
    times = np.linspace(0.0, 12.0 * period_s, 121)
    angle = 0.3 + 2.0e-6 * times + amplitude_rad * np.sin(frequency * times)

    fit = harmonic_regression(times, angle, (frequency,))

    assert len(fit.components) == 1
    component = fit.components[0]
    assert component.period_s == pytest.approx(period_s)
    assert component.amplitude_rad == pytest.approx(amplitude_rad, abs=1e-10)
    assert component.peak_to_peak_rad == pytest.approx(2.0 * amplitude_rad, abs=1e-10)
    assert fit.periodic_amplitude_rad == pytest.approx(amplitude_rad, abs=1e-10)


def test_multi_harmonic_rss_amplitude_has_components_with_individual_periods() -> None:
    periods = (1000.0, 2500.0)
    amplitudes = (0.1, 0.2)
    frequencies = tuple(2.0 * math.pi / period for period in periods)
    times = np.linspace(0.0, 50_000.0, 501)
    angle = (
        0.1
        + amplitudes[0] * np.sin(frequencies[0] * times)
        + amplitudes[1] * np.cos(frequencies[1] * times)
    )

    fit = harmonic_regression(times, angle, frequencies)

    assert [item.period_s for item in fit.components] == pytest.approx(periods)
    assert [item.amplitude_rad for item in fit.components] == pytest.approx(amplitudes, abs=1e-10)
    assert [item.peak_to_peak_rad for item in fit.components] == pytest.approx(
        [2.0 * value for value in amplitudes],
        abs=1e-10,
    )
    assert fit.periodic_amplitude_rad == pytest.approx(math.hypot(*amplitudes), abs=1e-10)


def test_short_horizon_recovers_secular_drift_with_annual_harmonic() -> None:
    # This is the failure mode seen in engineering review: a long-period basis
    # shares a short observation window with a very small secular rate. Raw
    # seconds in the linear least-squares column make the design matrix nearly
    # singular and can bias the inferred drift.
    times = np.linspace(0.0, 10.0 * 86400.0, 241)
    annual_frequency = 2.0 * math.pi / SIDEREAL_YEAR_S
    expected_rate_rad_s = 1.25e-11
    angle = (
        0.4
        + expected_rate_rad_s * times
        + 3.0e-4 * np.sin(annual_frequency * times)
        - 2.0e-4 * np.cos(annual_frequency * times)
    )

    fit = harmonic_regression(times, angle, (annual_frequency,))

    assert fit.secular_drift_rad_s == pytest.approx(expected_rate_rad_s, rel=2.0e-5, abs=1.0e-15)
    assert np.max(np.abs(fit.residual_rad)) < 1.0e-10
