from __future__ import annotations

import pytest

from constellation_control.optimization.operational_robustness import (
    CommonSampleSetIdentity,
    RealizationStatus,
    StrategyRealizationOutcome,
    StrategyRobustnessEvidence,
    aggregate_strategy_robustness,
    common_sample_set_from_generated,
    paired_metric_delta,
)
from constellation_control.uncertainty.campaign import (
    DistributionKind,
    RobustnessCampaignConfig,
    ScalarUncertaintyConfig,
    WorstDirection,
    generate_campaign_samples,
)


def _config(*, workers: int) -> RobustnessCampaignConfig:
    return RobustnessCampaignConfig(
        campaign_id="paired-operational-test",
        samples=3,
        workers=workers,
        seed=4713,
        accepted_candidate_id="candidate-A",
        scalar_uncertainties=(
            ScalarUncertaintyConfig(
                name="initial.GLO-01.delta_a_m",
                distribution=DistributionKind.NORMAL,
                sigma=10.0,
            ),
        ),
        worst_metric="fleet.delta_v_m_s",
        worst_direction=WorstDirection.MAX,
        resume=workers == 1,
    )


def _completed(common: CommonSampleSetIdentity, strategy_id: str, offset: float = 0.0) -> StrategyRobustnessEvidence:
    outcomes = tuple(
        StrategyRealizationOutcome(
            realization=sample.realization,
            sample_sha256=sample.sample_sha256,
            status=RealizationStatus.COMPLETED,
            metrics={"delta_v_m_s": float(sample.realization + 1) + offset},
            violations={"phase_corridor": sample.realization == 2},
            authority_backend="orekit-numerical-validation",
            authority_force_model_fingerprint="hf-fp",
        )
        for sample in common.samples
    )
    return StrategyRobustnessEvidence(
        strategy_id=strategy_id,
        common_samples=common,
        outcomes=outcomes,
    )


def test_existing_sampler_has_same_common_identity_when_only_worker_count_changes() -> None:
    one = _config(workers=1)
    many = _config(workers=8)
    samples_one = generate_campaign_samples(one)
    samples_many = generate_campaign_samples(many)

    common_one = common_sample_set_from_generated(one, samples_one)
    common_many = common_sample_set_from_generated(many, samples_many)

    assert common_one == common_many
    assert [item.sample_sha256 for item in common_one.samples] == [
        item["sample_sha256"] for item in samples_one
    ]
    restored = CommonSampleSetIdentity.model_validate_json(common_one.model_dump_json())
    assert restored == common_one


def test_failed_and_missing_realizations_remain_in_conservative_denominator() -> None:
    config = _config(workers=1)
    common = common_sample_set_from_generated(config, generate_campaign_samples(config))
    outcomes = (
        StrategyRealizationOutcome(
            realization=0,
            sample_sha256=common.samples[0].sample_sha256,
            status=RealizationStatus.COMPLETED,
            metrics={"delta_v_m_s": 1.0},
            violations={"phase_corridor": False, "minimum_pair_distance": False},
        ),
        StrategyRealizationOutcome(
            realization=1,
            sample_sha256=common.samples[1].sample_sha256,
            status=RealizationStatus.FAILED,
            failure_reason="numerical-authority-failed",
        ),
        StrategyRealizationOutcome(
            realization=2,
            sample_sha256=common.samples[2].sample_sha256,
            status=RealizationStatus.MISSING,
            failure_reason="result-not-produced",
        ),
    )
    evidence = StrategyRobustnessEvidence(
        strategy_id="candidate-A",
        common_samples=common,
        outcomes=outcomes,
    )
    aggregate = aggregate_strategy_robustness(evidence)

    assert aggregate.total_realizations == 3
    assert aggregate.completed_realizations == 1
    assert aggregate.failed_realizations == 1
    assert aggregate.missing_realizations == 1
    assert aggregate.incomplete_probability == pytest.approx(2.0 / 3.0)
    assert aggregate.conservative_violation_probability["phase_corridor"] == pytest.approx(2.0 / 3.0)
    assert aggregate.conservative_violation_probability["minimum_pair_distance"] == pytest.approx(2.0 / 3.0)
    assert aggregate.conservative_violation_probability["incomplete_realization"] == pytest.approx(2.0 / 3.0)
    assert aggregate.metric_statistics["delta_v_m_s"]["count"] == 1


def test_strategy_rows_must_cover_exact_common_realization_hashes() -> None:
    config = _config(workers=1)
    common = common_sample_set_from_generated(config, generate_campaign_samples(config))
    outcomes = list(_completed(common, "candidate-A").outcomes)
    outcomes[1] = outcomes[1].model_copy(update={"sample_sha256": "0" * 64})

    with pytest.raises(ValueError, match="sample hash"):
        StrategyRobustnessEvidence(
            strategy_id="candidate-A",
            common_samples=common,
            outcomes=tuple(outcomes),
        )


def test_paired_delta_uses_only_realizations_completed_by_both_strategies() -> None:
    config = _config(workers=1)
    common = common_sample_set_from_generated(config, generate_campaign_samples(config))
    left = _completed(common, "candidate-A", offset=1.0)
    right_full = _completed(common, "boundary-to-boundary", offset=0.0)
    right_outcomes = list(right_full.outcomes)
    right_outcomes[1] = StrategyRealizationOutcome(
        realization=1,
        sample_sha256=common.samples[1].sample_sha256,
        status=RealizationStatus.FAILED,
        failure_reason="authority-rejected",
    )
    right = StrategyRobustnessEvidence(
        strategy_id=right_full.strategy_id,
        common_samples=common,
        outcomes=tuple(right_outcomes),
    )

    delta = paired_metric_delta(left, right, "delta_v_m_s")

    assert delta.paired_complete_count == 2
    assert delta.mean_left_minus_right == pytest.approx(1.0)
    assert delta.minimum_left_minus_right == pytest.approx(1.0)
    assert delta.maximum_left_minus_right == pytest.approx(1.0)


def test_paired_comparison_rejects_different_common_sample_identity() -> None:
    config = _config(workers=1)
    common = common_sample_set_from_generated(config, generate_campaign_samples(config))
    left = _completed(common, "candidate-A")
    changed_sample = common.samples[0].model_copy(update={"sample_sha256": "f" * 64})
    changed_common = common.model_copy(update={"samples": (changed_sample, *common.samples[1:])})
    right = _completed(changed_common, "boundary-to-boundary")

    with pytest.raises(ValueError, match="identical common sample-set identity"):
        paired_metric_delta(left, right, "delta_v_m_s")
