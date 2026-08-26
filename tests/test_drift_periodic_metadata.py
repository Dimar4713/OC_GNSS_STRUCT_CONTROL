import math

import numpy as np
import pytest

from constellation_control.analysis.drift import harmonic_regression


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
