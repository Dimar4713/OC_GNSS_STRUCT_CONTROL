from __future__ import annotations

from collections.abc import Mapping, Sequence
from math import atan2, cos, sin, sqrt

import numpy as np

from constellation_control.domain.navigation import DopMetrics, NavigationSiteConfig


def geodetic_to_ecef_m(
    site: NavigationSiteConfig,
    *,
    reference_radius_m: float,
    flattening: float,
) -> np.ndarray:
    """Convert geodetic latitude/longitude/height to Earth-fixed Cartesian position."""

    if reference_radius_m <= 0.0:
        raise ValueError("reference_radius_m must be positive")
    if not 0.0 <= flattening < 1.0:
        raise ValueError("flattening must lie in [0, 1)")
    e2 = flattening * (2.0 - flattening)
    sin_lat = sin(site.latitude_rad)
    cos_lat = cos(site.latitude_rad)
    denominator = sqrt(1.0 - e2 * sin_lat * sin_lat)
    prime_vertical_radius = reference_radius_m / denominator
    radial = prime_vertical_radius + site.height_m
    polar = prime_vertical_radius * (1.0 - e2) + site.height_m
    return np.asarray(
        [
            radial * cos_lat * cos(site.longitude_rad),
            radial * cos_lat * sin(site.longitude_rad),
            polar * sin_lat,
        ],
        dtype=float,
    )


def inertial_to_ecef_m(r_inertial_m: Sequence[float], *, time_s: float, earth_rotation_rate_rad_s: float) -> np.ndarray:
    """Apply the explicit simple z-axis Earth rotation used by the reporting geometry layer.

    This is intentionally a named low-order transform, not a claim to replace an
    Orekit ITRF/EOP transform. Its algorithm identifier is persisted by callers.
    """

    vector = np.asarray(r_inertial_m, dtype=float)
    if vector.shape != (3,) or not np.all(np.isfinite(vector)):
        raise ValueError("inertial position must be a finite 3-vector")
    if not np.isfinite(time_s):
        raise ValueError("time_s must be finite")
    if earth_rotation_rate_rad_s <= 0.0 or not np.isfinite(earth_rotation_rate_rad_s):
        raise ValueError("earth_rotation_rate_rad_s must be positive and finite")
    theta = earth_rotation_rate_rad_s * time_s
    c = cos(theta)
    s = sin(theta)
    rotation = np.asarray([[c, s, 0.0], [-s, c, 0.0], [0.0, 0.0, 1.0]], dtype=float)
    return rotation @ vector


def ecef_delta_to_enu(delta_ecef_m: Sequence[float], site: NavigationSiteConfig) -> np.ndarray:
    """Rotate an Earth-fixed receiver-to-satellite vector into local ENU coordinates."""

    delta = np.asarray(delta_ecef_m, dtype=float)
    if delta.shape != (3,) or not np.all(np.isfinite(delta)):
        raise ValueError("ECEF delta must be a finite 3-vector")
    slon = sin(site.longitude_rad)
    clon = cos(site.longitude_rad)
    slat = sin(site.latitude_rad)
    clat = cos(site.latitude_rad)
    rotation = np.asarray(
        [
            [-slon, clon, 0.0],
            [-slat * clon, -slat * slon, clat],
            [clat * clon, clat * slon, slat],
        ],
        dtype=float,
    )
    return rotation @ delta


def elevation_rad(enu_m: Sequence[float]) -> float:
    enu = np.asarray(enu_m, dtype=float)
    if enu.shape != (3,) or not np.all(np.isfinite(enu)):
        raise ValueError("ENU vector must be a finite 3-vector")
    horizontal = float(np.hypot(enu[0], enu[1]))
    if horizontal == 0.0 and enu[2] == 0.0:
        raise ValueError("receiver-to-satellite vector must be non-zero")
    return atan2(float(enu[2]), horizontal)


def dop_from_enu_unit_vectors(
    visible_los_enu: Mapping[str, Sequence[float]],
) -> DopMetrics:
    """Compute GDOP/PDOP/HDOP/VDOP from visible local line-of-sight unit vectors.

    Fewer than four satellites or a rank-deficient geometry is represented as
    unavailable with no fabricated numeric DOP values.
    """

    satellite_ids = tuple(sorted(visible_los_enu))
    if len(satellite_ids) < 4:
        return DopMetrics(
            available=False,
            visible_satellite_ids=satellite_ids,
            reason="fewer-than-four-visible-satellites",
        )

    rows: list[list[float]] = []
    for satellite_id in satellite_ids:
        vector = np.asarray(visible_los_enu[satellite_id], dtype=float)
        if vector.shape != (3,) or not np.all(np.isfinite(vector)):
            raise ValueError(f"LOS for {satellite_id} must be a finite 3-vector")
        norm = float(np.linalg.norm(vector))
        if norm <= 0.0:
            raise ValueError(f"LOS for {satellite_id} must be non-zero")
        unit = vector / norm
        rows.append([float(unit[0]), float(unit[1]), float(unit[2]), 1.0])

    design = np.asarray(rows, dtype=float)
    normal = design.T @ design
    if np.linalg.matrix_rank(normal) < 4:
        return DopMetrics(
            available=False,
            visible_satellite_ids=satellite_ids,
            reason="rank-deficient-geometry",
        )
    try:
        covariance = np.linalg.inv(normal)
    except np.linalg.LinAlgError:
        return DopMetrics(
            available=False,
            visible_satellite_ids=satellite_ids,
            reason="singular-geometry",
        )
    diagonal = np.diag(covariance)
    if np.any(~np.isfinite(diagonal)) or np.any(diagonal <= 0.0):
        return DopMetrics(
            available=False,
            visible_satellite_ids=satellite_ids,
            reason="non-positive-dop-covariance",
        )
    hdop = sqrt(float(diagonal[0] + diagonal[1]))
    vdop = sqrt(float(diagonal[2]))
    pdop = sqrt(float(diagonal[0] + diagonal[1] + diagonal[2]))
    gdop = sqrt(float(np.sum(diagonal)))
    return DopMetrics(
        available=True,
        visible_satellite_ids=satellite_ids,
        gdop=gdop,
        pdop=pdop,
        hdop=hdop,
        vdop=vdop,
    )


def evaluate_navigation_geometry(
    satellite_inertial_positions_m: Mapping[str, Sequence[float]],
    *,
    time_s: float,
    site: NavigationSiteConfig,
    reference_radius_m: float,
    flattening: float,
    earth_rotation_rate_rad_s: float,
) -> DopMetrics:
    """Evaluate visibility and DOP for one explicit site and one propagation epoch."""

    receiver_ecef = geodetic_to_ecef_m(
        site,
        reference_radius_m=reference_radius_m,
        flattening=flattening,
    )
    visible: dict[str, np.ndarray] = {}
    for satellite_id, inertial_position in sorted(satellite_inertial_positions_m.items()):
        satellite_ecef = inertial_to_ecef_m(
            inertial_position,
            time_s=time_s,
            earth_rotation_rate_rad_s=earth_rotation_rate_rad_s,
        )
        enu = ecef_delta_to_enu(satellite_ecef - receiver_ecef, site)
        if elevation_rad(enu) >= site.elevation_mask_rad:
            visible[satellite_id] = enu / np.linalg.norm(enu)
    return dop_from_enu_unit_vectors(visible)
