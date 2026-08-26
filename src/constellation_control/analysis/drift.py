from __future__ import annotations

from dataclasses import dataclass
from math import pi

import numpy as np


SIDEREAL_DAY_S = 86164.0905
LUNAR_PERIOD_S = 27.321661 * 86400.0
SIDEREAL_YEAR_S = 365.25636 * 86400.0
DEFAULT_HARMONIC_LABELS = ("orbital", "sidereal_day", "lunar", "sidereal_year")


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


def default_harmonic_frequencies(orbital_period_s: float) -> tuple[float, ...]:
    periods = (orbital_period_s, SIDEREAL_DAY_S, LUNAR_PERIOD_S, SIDEREAL_YEAR_S)
    return tuple(2.0 * pi / period for period in periods)


def harmonic_regression(times_s: np.ndarray, angle_rad: np.ndarray, frequencies_rad_s: tuple[float, ...]) -> HarmonicFit:
    t = np.asarray(times_s, dtype=float)
    y = np.unwrap(np.asarray(angle_rad, dtype=float))
    columns: list[np.ndarray] = [np.ones_like(t), t]
    for frequency in frequencies_rad_s:
        columns.extend((np.sin(frequency * t), np.cos(frequency * t)))
    design = np.column_stack(columns)
    if design.shape[0] <= design.shape[1]:
        raise ValueError("harmonic regression needs more samples than fitted coefficients")
    coefficients, *_ = np.linalg.lstsq(design, y, rcond=None)
    fitted = design @ coefficients
    trend = coefficients[0] + coefficients[1] * t
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
        intercept_rad=float(coefficients[0]),
        secular_drift_rad_s=float(coefficients[1]),
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
