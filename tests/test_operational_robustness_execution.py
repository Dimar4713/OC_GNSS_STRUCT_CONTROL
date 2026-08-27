from __future__ import annotations

from collections.abc import Mapping

import pytest

from constellation_control.optimization.operational_robustness import (
    RealizationStatus,
    aggregate_strategy_robustness,
    paired_metric_delta,
)
from constellation_control.optimization.operational_robustness_execution import (
    CompletedOperationalRealization,
    run_operational_robustness_study,
)
from constellation_control.uncertainty.campaign import (
    DistributionKind,
    RobustnessCampaignConfig,
    ScalarUncertaintyConfig,
    WorstDirection,
    generate_campaign_samples,
)


FINGERPRINT = "a" * 64


def _config() -> RobustnessCampaignConfig:
    return RobustnessCampaignConfig(
        campaign_id="paired-operational-test",
        samples=4,
        workers=2,
        seed=4713,
        accepted_candidate_id="candidate-01",
        scalar_uncertainties=(
            ScalarUncertaintyConfig(
                name="initial.TEST.delta_a_m",
                distribution=DistributionKind.NORMAL,
                sigma=10.0,
            ),
        ),
        worst_metric="delta_v_m_s",
        worst_direction=WorstDirection.MAX,
        resume=False,
    )


def _completed(sample: Mapping[str, object], scale: float) -> CompletedOperationalRealization:
    realization = sample["realization"]
    sample_hash = sample["sample_sha256"]
    assert isinstance(realization, int)
    assert isinstance(sample_hash, str)
    return CompletedOperationalRealization(
        realization=realization,
        sample_sha256=sample_hash,
        metrics={"delta_v_m_s": scale + realization, "fuel_kg": 0.1 * scale + realization},
        violations={"phase_corridor": realization == 3},
        authority_backend="orekit-numerical-test",
        authority_force_model_fingerprint=FINGERPRINT,
    )


def test_multi_strategy_study_generates_samples_once_and_reuses_exact_order() -> None:
    config = _config()
    generator_calls = 0
    seen: dict[str, list[str]] = {}

    def generator(current: RobustnessCampaignConfig) -> tuple[dict[str, object], ...]:
        nonlocal generator_calls
        generator_calls += 1
        return generate_campaign_samples(current)

    def executor(strategy_id: str, scale: float):
        def run(sample: Mapping[str, object]) -> CompletedOperationalRealization:
            sample_hash = sample["sample_sha256"]
            assert isinstance(sample_hash, str)
            seen.setdefault(strategy_id, []).append(sample_hash)
            return _completed(sample, scale)

        return run

    result = run_operational_robustness_study(
        config,
        {
            "no-control": executor("no-control", 0.0),
            "rtc": executor("rtc", 1.0),
            "b2b": executor("b2b", 2.0),
            "candidate": executor("candidate", 3.0),
        },
        sample_generator=generator,
    )

    assert generator_calls == 1
    expected = [sample.sample_sha256 for sample in result.strategies[0].common_samples.samples]
    assert all(hashes == expected for hashes in seen.values())
    assert all(strategy.common_samples == result.strategies[0].common_samples for strategy in result.strategies)


def test_failed_and_missing_realizations_remain_in_conservative_denominator() -> None:
    config = _config()

    def executor(sample: Mapping[str, object]) -> CompletedOperationalRealization | None:
        realization = sample["realization"]
        assert isinstance(realization, int)
        if realization == 1:
            raise RuntimeError("numerical authority failed")
        if realization == 2:
            return None
        return _completed(sample, 1.0)

    result = run_operational_robustness_study(config, {"rtc": executor})
    evidence = result.strategies[0]
    assert [item.status for item in evidence.outcomes] == [
        RealizationStatus.COMPLETED,
        RealizationStatus.FAILED,
        RealizationStatus.MISSING,
        RealizationStatus.COMPLETED,
    ]
    aggregate = aggregate_strategy_robustness(evidence)
    assert aggregate.total_realizations == 4
    assert aggregate.completed_realizations == 2
    assert aggregate.failed_realizations == 1
    assert aggregate.missing_realizations == 1
    assert aggregate.incomplete_probability == pytest.approx(0.5)
    assert aggregate.conservative_violation_probability["phase_corridor"] == pytest.approx(0.75)


def test_completed_result_with_wrong_sample_identity_fails_closed() -> None:
    config = _config()

    def executor(sample: Mapping[str, object]) -> CompletedOperationalRealization:
        completed = _completed(sample, 1.0)
        if completed.realization == 0:
            return completed.model_copy(update={"sample_sha256": "b" * 64})
        return completed

    with pytest.raises(ValueError, match="sample hash"):
        run_operational_robustness_study(config, {"candidate": executor})


def test_completed_strategies_pair_through_existing_paired_evidence_contract() -> None:
    config = _config()
    result = run_operational_robustness_study(
        config,
        {
            "baseline": lambda sample: _completed(sample, 1.0),
            "candidate": lambda sample: _completed(sample, 0.5),
        },
    )
    by_id = {item.strategy_id: item for item in result.strategies}
    delta = paired_metric_delta(by_id["candidate"], by_id["baseline"], "delta_v_m_s")
    assert delta.paired_complete_count == 4
    assert delta.mean_left_minus_right == pytest.approx(-0.5)


def test_completed_realization_rejects_nonfinite_metric() -> None:
    with pytest.raises(ValueError, match="finite"):
        CompletedOperationalRealization(
            realization=0,
            sample_sha256="c" * 64,
            metrics={"delta_v_m_s": float("nan")},
            violations={},
            authority_backend="orekit-numerical-test",
            authority_force_model_fingerprint=FINGERPRINT,
        )
