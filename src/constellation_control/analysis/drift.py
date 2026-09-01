from __future__ import annotations

from dataclasses import dataclass
from math import pi

import numpy as np


SIDEREAL_DAY_S = 86164.0905
LUNAR_PERIOD_S = 27.321661 * 86400.0
SIDEREAL_YEAR_S = 365.25636 * 86400.0
DEFAULT_HARMONIC_LABELS = ("orbital", "sidereal_day", "lunar", "sidereal_year")
MINIMUM_OBSERVED_HARMONIC_CYCLES = 1.0


@dataclass(frozen=True)
class HarmonicComponent:
    frequency_rad_s: float
    period_s: float
    amplitude_rad: float
    peak_to_peak_rad: float


@dataclass(frozen=True)
class HarmonicFit:
    intercept_rad: float
    secular_drift_rad_s: float
    periodic_amplitude_rad: float
    fitted_rad: np.ndarray
    trend_rad: np.ndarray
    harmonic_rad: np.ndarray
    residual_rad: np.ndarray
    components: tuple[HarmonicComponent, ...]


@dataclass(frozen=True)
class HarmonicBasisTerm:
    label: str
    frequency_rad_s: float
    period_s: float
    observed_cycles: float
    included: bool
    exclusion_reason: str | None


@dataclass(frozen=True)
class HarmonicBasisSelection:
    observation_span_s: float
    minimum_observed_cycles: float
    terms: tuple[HarmonicBasisTerm, ...]

    @property
    def included_terms(self) -> tuple[HarmonicBasisTerm, ...]:
        return tuple(term for term in self.terms if term.included)

    @property
    def excluded_terms(self) -> tuple[HarmonicBasisTerm, ...]:
        return tuple(term for term in self.terms if not term.included)

    @property
    def included_frequencies_rad_s(self) -> tuple[float, ...]:
        return tuple(term.frequency_rad_s for term in self.included_terms)

    @property
    def included_labels(self) -> tuple[str, ...]:
        return tuple(term.label for term in self.included_terms)

    def as_dict(self) -> dict[str, object]:
        return {
            "authority": "observation-span-identifiable-harmonic-basis-v1",
            "observation_span_s": self.observation_span_s,
            "minimum_observed_cycles": self.minimum_observed_cycles,
            "policy": (
                "include a candidate harmonic only when the observation span contains "
                "at least one complete cycle; unresolved harmonics are excluded rather "
                "than regularized or constrained by a hidden prior"
            ),
            "terms": [term.__dict__ for term in self.terms],
            "included_labels": list(self.included_labels),
            "excluded_labels": [term.label for term in self.excluded_terms],
        }


def default_harmonic_frequencies(orbital_period_s: float) -> tuple[float, ...]:
    periods = (orbital_period_s, SIDEREAL_DAY_S, LUNAR_PERIOD_S, SIDEREAL_YEAR_S)
    return tuple(2.0 * pi / period for period in periods)


def select_identifiable_harmonic_basis(
    times_s: np.ndarray,
    frequencies_rad_s: tuple[float, ...],
    labels: tuple[str, ...] = DEFAULT_HARMONIC_LABELS,
    *,
    minimum_observed_cycles: float = MINIMUM_OBSERVED_HARMONIC_CYCLES,
) -> HarmonicBasisSelection:
    """Select only harmonic terms whose periods are observable on the supplied arc.

    This is an application-facing identifiability policy, not a regularizer.  A
    harmonic with less than ``minimum_observed_cycles`` over the observation span
    is excluded because its local sine/cosine arc cannot be separated safely from
    a secular trend without an external prior.
    """

    t = np.asarray(times_s, dtype=float)
    if t.ndim != 1 or t.size == 0 or not np.all(np.isfinite(t)):
        raise ValueError("harmonic basis selection requires a non-empty finite one-dimensional time array")
    if len(labels) != len(frequencies_rad_s):
        raise ValueError("harmonic basis labels and frequencies must have matching lengths")
    minimum_cycles = float(minimum_observed_cycles)
    if not np.isfinite(minimum_cycles) or minimum_cycles <= 0.0:
        raise ValueError("minimum_observed_cycles must be finite and positive")

    span_s = float(np.ptp(t))
    terms: list[HarmonicBasisTerm] = []
    for label, raw_frequency in zip(labels, frequencies_rad_s, strict=True):
        frequency = float(raw_frequency)
        if not np.isfinite(frequency) or frequency <= 0.0:
            raise ValueError("harmonic frequencies must be finite and positive")
        period_s = 2.0 * pi / frequency
        observed_cycles = span_s / period_s
        included = observed_cycles + 1.0e-12 >= minimum_cycles
        terms.append(
            HarmonicBasisTerm(
                label=str(label),
                frequency_rad_s=frequency,
                period_s=period_s,
                observed_cycles=observed_cycles,
                included=included,
                exclusion_reason=(
                    None
                    if included
                    else "observation_span_contains_less_than_minimum_cycles"
                ),
            )
        )
    return HarmonicBasisSelection(
        observation_span_s=span_s,
        minimum_observed_cycles=minimum_cycles,
        terms=tuple(terms),
    )


def harmonic_regression(times_s: np.ndarray, angle_rad: np.ndarray, frequencies_rad_s: tuple[float, ...]) -> HarmonicFit:
    t = np.asarray(times_s, dtype=float)
    y = np.unwrap(np.asarray(angle_rad, dtype=float))
    if t.ndim != 1 or y.ndim != 1 or t.shape != y.shape or t.size == 0:
        raise ValueError("harmonic regression requires matching non-empty one-dimensional time and angle arrays")
    if not np.all(np.isfinite(t)) or not np.all(np.isfinite(y)):
        raise ValueError("harmonic regression inputs must be finite")

    # Keep the physical harmonic arguments in SI seconds, but center and scale the
    # linear time basis before least squares. Using raw epoch seconds beside
    # O(1) sin/cos columns creates a severely ill-conditioned design matrix.
    #
    # This low-level routine intentionally fits exactly the basis supplied by the
    # caller. Application code must use ``select_identifiable_harmonic_basis``
    # before fitting default physical harmonics on finite observation arcs.
    t_center = float(t.mean())
    t_span = float(np.ptp(t))
    time_scale_s = t_span if t_span > 0.0 else 1.0
    t_scaled = (t - t_center) / time_scale_s

    columns: list[np.ndarray] = [np.ones_like(t), t_scaled]
    for frequency in frequencies_rad_s:
        if not np.isfinite(frequency) or frequency <= 0.0:
            raise ValueError("harmonic frequencies must be finite and positive")
        columns.extend((np.sin(frequency * t), np.cos(frequency * t)))
    design = np.column_stack(columns)
    if design.shape[0] <= design.shape[1]:
        raise ValueError("harmonic regression needs more samples than fitted coefficients")
    coefficients, *_ = np.linalg.lstsq(design, y, rcond=None)
    fitted = design @ coefficients
    secular_drift_rad_s = float(coefficients[1] / time_scale_s)
    intercept_rad = float(coefficients[0] - secular_drift_rad_s * t_center)
    trend = intercept_rad + secular_drift_rad_s * t
    harmonic = fitted - trend
    amplitudes: list[float] = []
    components: list[HarmonicComponent] = []
    for index, frequency in enumerate(frequencies_rad_s):
        a = coefficients[2 + 2 * index]
        b = coefficients[3 + 2 * index]
        amplitude = float(np.hypot(a, b))
        amplitudes.append(amplitude)
        period_s = 2.0 * pi / frequency
        components.append(
            HarmonicComponent(
                frequency_rad_s=float(frequency),
                period_s=float(period_s),
                amplitude_rad=amplitude,
                peak_to_peak_rad=2.0 * amplitude,
            )
        )
    return HarmonicFit(
        intercept_rad=intercept_rad,
        secular_drift_rad_s=secular_drift_rad_s,
        periodic_amplitude_rad=float(np.sqrt(np.sum(np.square(amplitudes)))),
        fitted_rad=fitted,
        trend_rad=trend,
        harmonic_rad=harmonic,
        residual_rad=y - fitted,
        components=tuple(components),
    )


def linear_rate(times_s: np.ndarray, values: np.ndarray) -> float:
    t = np.asarray(times_s, dtype=float)
    y = np.asarray(values, dtype=float)
    centered = t - t.mean()
    denominator = float(centered @ centered)
    if denominator == 0.0:
        return 0.0
    return float(centered @ (y - y.mean()) / denominator)