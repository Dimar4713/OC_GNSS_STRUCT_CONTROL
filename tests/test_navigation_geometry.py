from math import pi, sqrt

import numpy as np
import pytest

from constellation_control.analysis.navigation_geometry import (
    dop_from_enu_unit_vectors,
    ecef_delta_to_enu,
    elevation_rad,
    geodetic_to_ecef_m,
    inertial_to_ecef_m,
)
from constellation_control.domain.navigation import NavigationSiteConfig


def _equator_site() -> NavigationSiteConfig:
    return NavigationSiteConfig(
        site_id="equator-zero",
        latitude_rad=0.0,
        longitude_rad=0.0,
        height_m=0.0,
        elevation_mask_rad=0.0,
    )


def test_geodetic_equator_origin_maps_to_reference_radius() -> None:
    position = geodetic_to_ecef_m(_equator_site(), reference_radius_m=6_378_137.0, flattening=0.0)
    assert np.allclose(position, np.asarray([6_378_137.0, 0.0, 0.0]), atol=1.0e-9)


def test_simple_earth_rotation_has_explicit_sign_convention() -> None:
    omega = 1.0
    rotated = inertial_to_ecef_m((2.0, 0.0, 0.0), time_s=pi / 2.0, earth_rotation_rate_rad_s=omega)
    assert np.allclose(rotated, np.asarray([0.0, -2.0, 0.0]), atol=1.0e-12)


def test_ecef_to_enu_and_elevation_at_equator() -> None:
    site = _equator_site()
    # At lat=lon=0 the local Up axis is +ECEF X, East is +Y, North is +Z.
    enu = ecef_delta_to_enu((10.0, 20.0, 30.0), site)
    assert np.allclose(enu, np.asarray([20.0, 30.0, 10.0]))
    assert elevation_rad((0.0, 0.0, 1.0)) == pytest.approx(pi / 2.0)
    assert elevation_rad((1.0, 0.0, 0.0)) == pytest.approx(0.0)


def test_symmetric_tetrahedral_geometry_has_known_dops() -> None:
    root3 = sqrt(3.0)
    los = {
        "S1": (1.0 / root3, 1.0 / root3, 1.0 / root3),
        "S2": (1.0 / root3, -1.0 / root3, -1.0 / root3),
        "S3": (-1.0 / root3, 1.0 / root3, -1.0 / root3),
        "S4": (-1.0 / root3, -1.0 / root3, 1.0 / root3),
    }
    metrics = dop_from_enu_unit_vectors(los)
    assert metrics.available
    assert metrics.pdop == pytest.approx(1.5, abs=1.0e-12)
    assert metrics.hdop == pytest.approx(sqrt(1.5), abs=1.0e-12)
    assert metrics.vdop == pytest.approx(sqrt(0.75), abs=1.0e-12)
    assert metrics.gdop == pytest.approx(sqrt(2.5), abs=1.0e-12)


def test_insufficient_or_rank_deficient_geometry_is_unavailable() -> None:
    insufficient = dop_from_enu_unit_vectors(
        {
            "S1": (1.0, 0.0, 1.0),
            "S2": (0.0, 1.0, 1.0),
            "S3": (-1.0, 0.0, 1.0),
        }
    )
    assert not insufficient.available
    assert insufficient.pdop is None
    assert insufficient.reason == "fewer-than-four-visible-satellites"

    rank_deficient = dop_from_enu_unit_vectors(
        {
            "S1": (0.0, 0.0, 1.0),
            "S2": (0.0, 0.0, 2.0),
            "S3": (0.0, 0.0, 3.0),
            "S4": (0.0, 0.0, 4.0),
        }
    )
    assert not rank_deficient.available
    assert rank_deficient.gdop is None
    assert rank_deficient.reason == "rank-deficient-geometry"
