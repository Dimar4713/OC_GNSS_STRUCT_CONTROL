from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable
from typing import cast

from constellation_control.domain.models import MeanOrbit, SatelliteSpec

TAU = 2.0 * math.pi


def wrap_rad(angle_rad: float) -> float:
    """Wrap an angle to [0, 2*pi)."""
    return angle_rad % TAU


def wrap_deg(angle_deg: float) -> float:
    """Wrap an angle to [0, 360)."""
    return angle_deg % 360.0


def signed_angle_deg(angle_deg: float) -> float:
    """Wrap an angular difference to [-180, 180)."""
    return (angle_deg + 180.0) % 360.0 - 180.0


def mean_orbit_engineering_elements(mean_orbit: MeanOrbit, mu_m3_s2: float) -> dict[str, float]:
    """Derive operator-facing quantities from the authoritative mean equinoctial state.

    The repository's ``ix``/``iy`` fields correspond to the equinoctial inclination
    components h_x/h_y = tan(i/2) * [cos(Omega), sin(Omega)].  ``lambda_rad`` is
    the mean longitude.  Therefore ``u_mean = lambda - Omega`` is the mean
    argument-of-latitude-like phase M + omega.  It must not be labelled as an
    osculating argument of latitude.
    """
    if mu_m3_s2 <= 0.0:
        raise ValueError("mu_m3_s2 must be positive")

    inclination_rad = 2.0 * math.atan(math.hypot(mean_orbit.ix, mean_orbit.iy))
    raan_rad = wrap_rad(math.atan2(mean_orbit.iy, mean_orbit.ix))
    u_mean_rad = wrap_rad(mean_orbit.lambda_rad - raan_rad)
    period_s = TAU * math.sqrt(mean_orbit.a_m**3 / mu_m3_s2)

    return {
        "period_s": period_s,
        "period_h": period_s / 3600.0,
        "a_mean_m": mean_orbit.a_m,
        "a_mean_km": mean_orbit.a_m / 1000.0,
        "inclination_rad": inclination_rad,
        "inclination_deg": math.degrees(inclination_rad),
        "raan_rad": raan_rad,
        "raan_deg": math.degrees(raan_rad),
        "u_mean_rad": u_mean_rad,
        "u_mean_deg": math.degrees(u_mean_rad),
        "lambda_rad": mean_orbit.lambda_rad,
        "lambda_deg_wrapped": wrap_deg(math.degrees(mean_orbit.lambda_rad)),
    }


def _circular_mean_deg(values_deg: Iterable[float]) -> float:
    values = list(values_deg)
    if not values:
        raise ValueError("circular mean requires at least one angle")
    x = sum(math.cos(math.radians(value)) for value in values)
    y = sum(math.sin(math.radians(value)) for value in values)
    if math.isclose(x, 0.0, abs_tol=1e-15) and math.isclose(y, 0.0, abs_tol=1e-15):
        raise ValueError("circular mean is undefined for this angle set")
    return wrap_deg(math.degrees(math.atan2(y, x)))


def _cyclic_spacings_deg(phases_deg: list[float]) -> list[float]:
    if len(phases_deg) < 2:
        return []
    phases = sorted(wrap_deg(value) for value in phases_deg)
    spacings = [phases[index + 1] - phases[index] for index in range(len(phases) - 1)]
    spacings.append(phases[0] + 360.0 - phases[-1])
    return spacings


def constellation_geometry_preflight(
    satellites: Iterable[SatelliteSpec],
    mu_m3_s2: float,
) -> dict[str, object]:
    """Describe actual constellation geometry without inventing target values.

    Plane-to-plane phase offsets are reported modulo the nominal slot size only
    when both planes have the same population.  This makes regular Walker-like
    phasing visible while avoiding a claim that the observed offset is a design
    requirement.
    """
    grouped: dict[str, list[SatelliteSpec]] = defaultdict(list)
    for satellite in satellites:
        grouped[satellite.plane_id].append(satellite)

    planes: list[dict[str, object]] = []
    by_plane: dict[str, dict[str, object]] = {}
    for plane_id in sorted(grouped):
        members = grouped[plane_id]
        derived = [mean_orbit_engineering_elements(sat.mean_orbit, mu_m3_s2) for sat in members]
        phases = [float(item["u_mean_deg"]) for item in derived]
        raan_values = [float(item["raan_deg"]) for item in derived]
        inclination_values = [float(item["inclination_deg"]) for item in derived]
        spacings = _cyclic_spacings_deg(phases)
        plane = {
            "plane_id": plane_id,
            "satellite_count": len(members),
            "raan_mean_deg": _circular_mean_deg(raan_values),
            "inclination_mean_deg": sum(inclination_values) / len(inclination_values),
            "u_mean_deg_sorted": sorted(wrap_deg(value) for value in phases),
            "in_plane_spacing_deg": spacings,
            "in_plane_spacing_mean_deg": (sum(spacings) / len(spacings)) if spacings else None,
            "satellite_ids": [sat.satellite_id for sat in members],
        }
        planes.append(plane)
        by_plane[plane_id] = plane

    interplane: list[dict[str, object]] = []
    plane_ids = sorted(by_plane)
    if plane_ids:
        reference_id = plane_ids[0]
        reference = by_plane[reference_id]
        ref_phases = cast(list[float], reference["u_mean_deg_sorted"])
        ref_count = cast(int, reference["satellite_count"])
        ref_first = ref_phases[0] if ref_phases else 0.0
        for plane_id in plane_ids[1:]:
            current = by_plane[plane_id]
            current_phases = cast(list[float], current["u_mean_deg_sorted"])
            current_count = cast(int, current["satellite_count"])
            raan_delta = wrap_deg(float(current["raan_mean_deg"]) - float(reference["raan_mean_deg"]))
            record: dict[str, object] = {
                "reference_plane_id": reference_id,
                "plane_id": plane_id,
                "raan_offset_deg": raan_delta,
                "phase_offset_mod_slot_deg": None,
            }
            if current_count == ref_count and ref_count > 0 and current_phases and ref_phases:
                slot_deg = 360.0 / ref_count
                record["phase_offset_mod_slot_deg"] = wrap_deg(current_phases[0] - ref_first) % slot_deg
                record["slot_deg"] = slot_deg
            interplane.append(record)

    return {
        "plane_count": len(planes),
        "satellite_count": sum(len(items) for items in grouped.values()),
        "planes": planes,
        "interplane": interplane,
        "semantics_ru": (
            "u_mean = lambda - Omega — средняя фазовая координата M+omega, полученная из средних "
            "эквиноциальных элементов; это не оскулирующий аргумент широты."
        ),
        "semantics_en": (
            "u_mean = lambda - Omega is the mean phase coordinate M+omega derived from mean "
            "equinoctial elements; it is not an osculating argument of latitude."
        ),
    }
