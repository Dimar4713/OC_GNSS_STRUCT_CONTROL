from pathlib import Path

from constellation_control.application.robustness import (
    apply_uncertainty_sample,
    load_robustness_application_config,
)
from constellation_control.application.run import load_scenario


SCENARIO = Path("scenarios/orekit_linearization_smoke.yaml")
CAMPAIGN = Path("scenarios/robustness_campaign_smoke.yaml")


def test_full_realization_seed_is_preserved_outside_java_wire_contract() -> None:
    scenario = load_scenario(SCENARIO)
    config = load_robustness_application_config(CAMPAIGN)
    full_seed = 2**62 + 123456789
    sample: dict[str, object] = {
        "realization_seed": full_seed,
        "sample_sha256": "lineage-placeholder",
    }

    applied = apply_uncertainty_sample(scenario, config, sample)

    assert sample["realization_seed"] == full_seed
    assert applied.request.seed == full_seed % (2**31 - 1)
    assert 0 <= applied.request.seed < 2**31 - 1
