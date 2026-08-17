from pathlib import Path

import numpy as np
import pytest

from constellation_control.application.robustness import (
    RobustnessApplicationConfig,
    RobustnessAuthorityConfig,
    apply_uncertainty_sample,
    validate_uncertainty_contract,
)
from constellation_control.application.run import load_scenario
from constellation_control.domain.models import Maneuver
from constellation_control.uncertainty.campaign import (
    CorrelatedNormalGroupConfig,
    DistributionKind,
    RobustnessCampaignConfig,
    ScalarUncertaintyConfig,
)


SCENARIO = Path("scenarios/orekit_linearization_smoke.yaml")
DATA_REVISION = "baf158744d38ec76cf94e2d396280d545b9f0ba2"
DATA_SHA = "7c0387b0bf7f08f0393b724090c9b926870cae4dde1d02823d57291eab0a3fcf"


def _authority() -> RobustnessAuthorityConfig:
    return RobustnessAuthorityConfig(
        orekit_version="13.1.7",
        gravity_model="EIGEN-6S",
        orekit_data_revision=DATA_REVISION,
        orekit_data_sha256=DATA_SHA,
    )


def _baseline() -> tuple[Maneuver, ...]:
    return (Maneuver(satellite_id="LIN-DEP", time_s=10.0, dv_rtn_m_s=(0.01, 0.02, 0.03)),)


def _campaign(*uncertainties: ScalarUncertaintyConfig) -> RobustnessCampaignConfig:
    return RobustnessCampaignConfig(
        campaign_id="application-mapping-test",
        samples=4,
        workers=2,
        seed=4713,
        accepted_candidate_id="accepted-design-001",
        scalar_uncertainties=uncertainties,
        correlated_normal_groups=(
            CorrelatedNormalGroupConfig(
                group_id="od-state",
                names=("od.LIN-DEP.delta_ex", "od.LIN-DEP.delta_ey"),
                covariance=((1.0e-10, 2.0e-11), (2.0e-11, 1.5e-10)),
            ),
        ),
        worst_metric="fleet.total_delta_v_m_s",
    )


def _config(*uncertainties: ScalarUncertaintyConfig) -> RobustnessApplicationConfig:
    return RobustnessApplicationConfig(
        campaign=_campaign(*uncertainties),
        authority=_authority(),
        baseline_maneuvers=_baseline(),
    )


def test_uncertainty_contract_accepts_all_operational_source_families() -> None:
    scenario = load_scenario(SCENARIO)
    config = _config(
        ScalarUncertaintyConfig(
            name="initial.LIN-DEP.delta_a_m",
            distribution=DistributionKind.NORMAL,
            sigma=10.0,
        ),
        ScalarUncertaintyConfig(
            name="slot.LIN-DEP.delta_lambda_rad",
            distribution=DistributionKind.NORMAL,
            sigma=1.0e-5,
        ),
        ScalarUncertaintyConfig(
            name="spacecraft.LIN-DEP.cr_area_over_mass_fraction",
            distribution=DistributionKind.NORMAL,
            sigma=0.01,
        ),
        ScalarUncertaintyConfig(
            name="maneuver.0.magnitude_fraction",
            distribution=DistributionKind.NORMAL,
            sigma=0.01,
        ),
        ScalarUncertaintyConfig(
            name="maneuver.0.direction_r_rad",
            distribution=DistributionKind.NORMAL,
            sigma=1.0e-4,
        ),
        ScalarUncertaintyConfig(
            name="maneuver.0.timing_error_s",
            distribution=DistributionKind.UNIFORM,
            low=-1.0,
            high=1.0,
        ),
        ScalarUncertaintyConfig(
            name="window.0.unavailable",
            distribution=DistributionKind.BERNOULLI,
            probability_true=0.1,
        ),
    )
    validate_uncertainty_contract(scenario, config)


def test_uncertainty_contract_rejects_unknown_or_wrongly_typed_variables() -> None:
    scenario = load_scenario(SCENARIO)
    unknown = _config(
        ScalarUncertaintyConfig(
            name="initial.LIN-DEP.delta_typo",
            distribution=DistributionKind.NORMAL,
            sigma=1.0,
        )
    )
    with pytest.raises(ValueError, match="unknown robustness uncertainty"):
        validate_uncertainty_contract(scenario, unknown)

    wrong_window_type = _config(
        ScalarUncertaintyConfig(
            name="window.0.unavailable",
            distribution=DistributionKind.NORMAL,
            sigma=1.0,
        )
    )
    with pytest.raises(ValueError, match="must be Bernoulli"):
        validate_uncertainty_contract(scenario, wrong_window_type)


def test_sample_mapping_combines_initial_od_slot_spacecraft_and_maneuver_errors() -> None:
    scenario = load_scenario(SCENARIO)
    config = _config(
        ScalarUncertaintyConfig(
            name="initial.LIN-DEP.delta_a_m",
            distribution=DistributionKind.NORMAL,
            sigma=1.0,
        )
    )
    by_id = {sat.satellite_id: sat for sat in scenario.constellation.satellites}
    nominal = by_id["LIN-DEP"]
    sample: dict[str, object] = {
        "realization_seed": 9001,
        "initial.LIN-DEP.delta_a_m": 10.0,
        "od.LIN-DEP.delta_a_m": 2.0,
        "initial.LIN-DEP.delta_ex": 1.0e-5,
        "od.LIN-DEP.delta_ex": -2.0e-6,
        "slot.LIN-DEP.delta_lambda_rad": 3.0e-5,
        "spacecraft.LIN-DEP.cr_area_over_mass_fraction": 0.01,
        "maneuver.0.magnitude_fraction": 0.10,
        "maneuver.0.direction_r_rad": 1.0e-3,
        "maneuver.0.direction_t_rad": -2.0e-3,
        "maneuver.0.direction_n_rad": 3.0e-3,
        "maneuver.0.timing_error_s": 2.5,
        "window.0.unavailable": False,
    }
    applied = apply_uncertainty_sample(scenario, config, sample)
    perturbed = next(sat for sat in applied.request.satellites if sat.satellite_id == "LIN-DEP")

    assert perturbed.mean_orbit.a_m == pytest.approx(nominal.mean_orbit.a_m + 12.0)
    assert perturbed.mean_orbit.ex == pytest.approx(nominal.mean_orbit.ex + 8.0e-6)
    assert perturbed.mean_orbit.lambda_rad == pytest.approx(nominal.mean_orbit.lambda_rad + 3.0e-5)
    assert perturbed.spacecraft.cr == pytest.approx(nominal.spacecraft.cr * 1.01)
    assert applied.request.seed == 9001
    assert len(applied.request.maneuvers) == 1
    maneuver = applied.request.maneuvers[0]
    assert maneuver.time_s == pytest.approx(12.5)
    nominal_dv = np.asarray(config.baseline_maneuvers[0].dv_rtn_m_s)
    rotation = np.asarray([1.0e-3, -2.0e-3, 3.0e-3])
    expected_dv = 1.10 * nominal_dv + np.cross(rotation, nominal_dv)
    assert np.allclose(np.asarray(maneuver.dv_rtn_m_s), expected_dv)
    assert applied.dropped_maneuver_indices == ()


def test_unavailable_window_drops_maneuver_explicitly() -> None:
    scenario = load_scenario(SCENARIO)
    config = _config(
        ScalarUncertaintyConfig(
            name="window.0.unavailable",
            distribution=DistributionKind.BERNOULLI,
            probability_true=0.5,
        )
    )
    applied = apply_uncertainty_sample(
        scenario,
        config,
        {"realization_seed": 7, "window.0.unavailable": True},
    )
    assert applied.request.maneuvers == ()
    assert applied.dropped_maneuver_indices == (0,)
