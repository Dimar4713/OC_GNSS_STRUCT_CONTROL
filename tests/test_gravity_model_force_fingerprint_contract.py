from constellation_control.domain.models import ForceModelConfig, ForceMode, GravityModelName


def _force(degree: int, order: int) -> ForceModelConfig:
    return ForceModelConfig(
        mode=ForceMode.VALIDATION,
        gravity_model=GravityModelName.EIGEN_6S,
        mu_m3_s2=3.986004418e14,
        reference_radius_m=6378137.0,
        flattening=0.0033528106647474805,
        j2=0.00108262668,
        earth_rotation_rate_rad_s=7.2921150e-5,
        gravity_degree=degree,
        gravity_order=order,
        moon=True,
        sun=True,
        srp=True,
    )


def test_gravity_degree_order_change_force_model_fingerprint() -> None:
    fingerprints = {_force(n, m).fingerprint() for n, m in ((0, 0), (2, 0), (8, 8), (32, 32))}
    assert len(fingerprints) == 4
