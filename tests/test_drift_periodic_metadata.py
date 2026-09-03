import math

import numpy as np
import pytest

from constellation_control.analysis.drift import (
    DEFAULT_HARMONIC_LABELS,
    SIDEREAL_YEAR_S,
    default_harmonic_frequencies,
    harmonic_regression,
    linear_rate,
    select_identifiable_harmonic_basis,
)


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
    # Low-level harmonic_regression deliberately fits the explicitly requested
    # basis. This regression protects the time centering/scaling fix from #158.
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


def test_six_hour_gnss_arc_excludes_all_unresolved_default_harmonics() -> None:
    times = np.linspace(0.0, 6.0 * 3600.0, 25)
    orbital_period_s = 43_077.757
    frequencies = default_harmonic_frequencies(orbital_period_s)

    selection = select_identifiable_harmonic_basis(times, frequencies)

    assert selection.observation_span_s == pytest.approx(21_600.0)
    assert selection.minimum_observed_cycles == 1.0
    assert selection.included_frequencies_rad_s == ()
    assert selection.included_labels == ()
    assert [term.label for term in selection.excluded_terms] == list(DEFAULT_HARMONIC_LABELS)
    assert all(term.observed_cycles < 1.0 for term in selection.excluded_terms)
    assert all(
        term.exclusion_reason == "observation_span_contains_less_than_minimum_cycles"
        for term in selection.excluded_terms
    )


def test_application_basis_short_arc_reduces_to_direct_linear_secular_rate() -> None:
    times = np.linspace(0.0, 6.0 * 3600.0, 25)
    orbital_period_s = 43_077.757
    frequencies = default_harmonic_frequencies(orbital_period_s)
    # Small secular drift plus curvature from a harmonic that is not observable
    # over a complete cycle. The application policy must not claim that the
    # long-period component has been independently estimated.
    angle = (
        0.7853978
        + 1.1e-10 * times
        + 8.0e-7 * np.sin(2.0 * math.pi * times / (2.5 * 86400.0))
    )

    selection = select_identifiable_harmonic_basis(times, frequencies)
    fit = harmonic_regression(times, angle, selection.included_frequencies_rad_s)
    expected_direct_rate = linear_rate(times, np.unwrap(angle))

    assert selection.included_frequencies_rad_s == ()
    assert fit.components == ()
    assert fit.periodic_amplitude_rad == 0.0
    assert fit.secular_drift_rad_s == pytest.approx(expected_direct_rate, rel=1e-12, abs=1e-18)


def test_seven_point_180_second_preview_arc_uses_linear_only_fit() -> None:
    """Regression for the operator-reported 180 s / 30 s Preview run.

    A seven-sample engineering smoke arc cannot identify any of the default GNSS
    physical harmonics. Application-facing basis selection must therefore reduce
    the fit to intercept + secular slope instead of forwarding four harmonics to
    the low-level least-squares routine and failing on coefficient count.
    """

    times = np.arange(0.0, 181.0, 30.0)
    orbital_period_s = 43_077.757
    candidate_frequencies = default_harmonic_frequencies(orbital_period_s)
    expected_rate_rad_s = 2.5e-9
    angle = 0.42 + expected_rate_rad_s * times

    selection = select_identifiable_harmonic_basis(times, candidate_frequencies)
    fit = harmonic_regression(times, angle, selection.included_frequencies_rad_s)

    assert times.size == 7
    assert selection.observation_span_s == pytest.approx(180.0)
    assert selection.included_frequencies_rad_s == ()
    assert selection.included_labels == ()
    assert fit.components == ()
    assert fit.periodic_amplitude_rad == 0.0
    assert fit.secular_drift_rad_s == pytest.approx(expected_rate_rad_s, rel=1e-10, abs=1e-15)


def test_basis_selection_admits_harmonics_only_after_complete_cycles() -> None:
    orbital_period_s = 12.0 * 3600.0
    frequencies = default_harmonic_frequencies(orbital_period_s)
    times = np.linspace(0.0, 24.0 * 3600.0, 97)

    selection = select_identifiable_harmonic_basis(times, frequencies)

    assert selection.included_labels == ("orbital", "sidereal_day")
    assert [term.label for term in selection.excluded_terms] == ["lunar", "sidereal_year"]
    assert selection.included_terms[0].observed_cycles == pytest.approx(2.0)
    assert selection.included_terms[1].observed_cycles > 1.0
