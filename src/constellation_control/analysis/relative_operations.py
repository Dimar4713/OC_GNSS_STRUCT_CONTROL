from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import atan2, degrees, pi

import numpy as np

from constellation_control.analysis.drift import linear_rate
from constellation_control.domain.models import MeanOrbit
from constellation_control.dynamics.orbits import wrap_pi

DAY_S = 86400.0
JULIAN_YEAR_S = 365.25 * DAY_S


@dataclass(frozen=True)
class AngularRateEngineeringUnits:
    rad_s: float
    deg_day: float
    deg_julian_year: float


@dataclass(frozen=True)
class PhaseCorridorForecast:
    half_width_rad: float
    half_width_deg: float
    current_delta_u_rad: float
    current_delta_u_deg: float
    inside_corridor: bool
    predicted_boundary_rad: float | None
    predicted_boundary_deg: float | None
    time_to_boundary_s: float | None
    time_to_boundary_days: float | None


@dataclass(frozen=True)
class RelativeOperationsDiagnostics:
    initial_delta_u_rad: float
    final_delta_u_rad: float
    initial_delta_u_deg: float
    final_delta_u_deg: float
    secular_delta_u_rate_rad_s: float
    secular_delta_u_rate_deg_day: float
    secular_delta_u_rate_deg_julian_year: float
    initial_along_track_proxy_m: float
    final_along_track_proxy_m: float
    secular_along_track_proxy_rate_m_s: float


def angular_rate_engineering_units(rate_rad_s: float) -> AngularRateEngineeringUnits:
    rate = float(rate_rad_s)
    deg_s = degrees(rate)
    return AngularRateEngineeringUnits(
        rad_s=rate,
        deg_day=deg_s * DAY_S,
        deg_julian_year=deg_s * JULIAN_YEAR_S,
    )


def mean_phase_rad(mean_orbit: MeanOrbit) -> float:
    """Return mean phase u_mean = lambda - Omega, wrapped to [-pi, pi).

    The equinoctial inclination components follow ix = tan(i/2) cos(Omega)
    and iy = tan(i/2) sin(Omega). This quantity is therefore M + omega for
    the mean element set. It is not an osculating argument of latitude.
    """

    raan_rad = atan2(mean_orbit.iy, mean_orbit.ix)
    return wrap_pi(mean_orbit.lambda_rad - raan_rad)


def relative_mean_phase_series_rad(
    reference: Sequence[MeanOrbit],
    deputy: Sequence[MeanOrbit],
) -> np.ndarray:
    if len(reference) != len(deputy):
        raise ValueError("reference and deputy mean histories must have equal length")
    if not reference:
        raise ValueError("relative mean-phase history must not be empty")
    wrapped = np.asarray(
        [
            wrap_pi(mean_phase_rad(dep) - mean_phase_rad(ref))
            for ref, dep in zip(reference, deputy, strict=True)
        ],
        dtype=float,
    )
    return np.unwrap(wrapped)


def along_track_arc_proxy_m(delta_u_rad: np.ndarray, reference_a_m: np.ndarray) -> np.ndarray:
    phase = np.asarray(delta_u_rad, dtype=float)
    radius = np.asarray(reference_a_m, dtype=float)
    if phase.shape != radius.shape:
        raise ValueError("delta_u_rad and reference_a_m must have matching shapes")
    if phase.ndim != 1:
        raise ValueError("along-track proxy inputs must be one-dimensional")
    if not np.all(np.isfinite(phase)) or not np.all(np.isfinite(radius)) or np.any(radius <= 0.0):
        raise ValueError("along-track proxy inputs must be finite and reference_a_m positive")
    return radius * phase


def forecast_phase_corridor(
    current_delta_u_rad: float,
    secular_delta_u_rate_rad_s: float,
    half_width_rad: float,
) -> PhaseCorridorForecast:
    current = float(current_delta_u_rad)
    rate = float(secular_delta_u_rate_rad_s)
    half_width = float(half_width_rad)
    if not np.isfinite(current) or not np.isfinite(rate):
        raise ValueError("phase corridor state and rate must be finite")
    if not np.isfinite(half_width) or half_width <= 0.0 or half_width >= pi:
        raise ValueError("phase corridor half-width must be finite and inside (0, pi)")

    inside = abs(current) <= half_width
    boundary: float | None = None
    time_s: float | None = None
    if not inside:
        time_s = 0.0
        boundary = half_width if current > 0.0 else -half_width
    elif rate > 0.0:
        boundary = half_width
        time_s = max(0.0, (boundary - current) / rate)
    elif rate < 0.0:
        boundary = -half_width
        time_s = max(0.0, (boundary - current) / rate)

    return PhaseCorridorForecast(
        half_width_rad=half_width,
        half_width_deg=degrees(half_width),
        current_delta_u_rad=current,
        current_delta_u_deg=degrees(current),
        inside_corridor=inside,
        predicted_boundary_rad=boundary,
        predicted_boundary_deg=None if boundary is None else degrees(boundary),
        time_to_boundary_s=time_s,
        time_to_boundary_days=None if time_s is None else time_s / DAY_S,
    )


def analyze_relative_operations(
    times_s: np.ndarray,
    reference: Sequence[MeanOrbit],
    deputy: Sequence[MeanOrbit],
) -> tuple[RelativeOperationsDiagnostics, np.ndarray, np.ndarray]:
    times = np.asarray(times_s, dtype=float)
    if times.ndim != 1 or times.size != len(reference) or times.size < 2:
        raise ValueError("times_s must match non-empty mean histories and contain at least two samples")
    if not np.all(np.isfinite(times)) or np.any(np.diff(times) <= 0.0):
        raise ValueError("times_s must be finite and strictly increasing")

    delta_u = relative_mean_phase_series_rad(reference, deputy)
    reference_a = np.asarray([item.a_m for item in reference], dtype=float)
    along_track = along_track_arc_proxy_m(delta_u, reference_a)
    angular_rate = linear_rate(times, delta_u)
    along_track_rate = linear_rate(times, along_track)
    units = angular_rate_engineering_units(angular_rate)

    return (
        RelativeOperationsDiagnostics(
            initial_delta_u_rad=float(delta_u[0]),
            final_delta_u_rad=float(delta_u[-1]),
            initial_delta_u_deg=float(delta_u[0] * 180.0 / pi),
            final_delta_u_deg=float(delta_u[-1] * 180.0 / pi),
            secular_delta_u_rate_rad_s=units.rad_s,
            secular_delta_u_rate_deg_day=units.deg_day,
            secular_delta_u_rate_deg_julian_year=units.deg_julian_year,
            initial_along_track_proxy_m=float(along_track[0]),
            final_along_track_proxy_m=float(along_track[-1]),
            secular_along_track_proxy_rate_m_s=float(along_track_rate),
        ),
        delta_u,
        along_track,
    )
