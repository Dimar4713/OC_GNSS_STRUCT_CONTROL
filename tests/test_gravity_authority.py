import pytest
from pydantic import ValidationError

from constellation_control.domain.models import ForceModelConfig, ForceMode, GravityModelName


def _kwargs() -> dict[str, object]:
    return {
        "mu_m3_s2": 3.986004418e14,
        "reference_radius_m": 6_378_137.0,
        "flattening": 1.0 / 298.257223563,
        "j2": 0.00108262668,
        "earth_rotation_rate_rad_s": 7.292115e-5,
        "gravity_degree": 8,
        "gravity_order": 8,
        "moon": True,
        "sun": True,
        "srp": True,
    }


def test_screening_does_not_require_high_fidelity_gravity_authority() -> None:
    model = ForceModelConfig(mode=ForceMode.SCREENING, **_kwargs())
    assert model.gravity_model is None


@pytest.mark.parametrize("mode", [ForceMode.DESIGN, ForceMode.VALIDATION])
def test_high_fidelity_force_model_requires_explicit_gravity_authority(mode: ForceMode) -> None:
    with pytest.raises(ValidationError, match="explicit gravity_model"):
        ForceModelConfig(mode=mode, **_kwargs())


def test_eigen_6s_is_part_of_force_model_fingerprint() -> None:
    high_fidelity = ForceModelConfig(
        mode=ForceMode.VALIDATION,
        gravity_model=GravityModelName.EIGEN_6S,
        **_kwargs(),
    )
    screening = ForceModelConfig(mode=ForceMode.SCREENING, **_kwargs())
    assert high_fidelity.gravity_model == GravityModelName.EIGEN_6S
    assert high_fidelity.fingerprint() != screening.fingerprint()
    assert len(high_fidelity.fingerprint()) == 64
