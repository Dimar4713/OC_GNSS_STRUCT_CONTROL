from __future__ import annotations

from pathlib import Path

import numpy as np

from constellation_control.uncertainty.campaign import (
    CorrelatedNormalGroupConfig,
    DistributionKind,
    RobustnessCampaignConfig,
    ScalarUncertaintyConfig,
    WorstDirection,
    generate_campaign_samples,
    run_robustness_campaign,
)


def _config(workers: int, *, resume: bool = True) -> RobustnessCampaignConfig:
    return RobustnessCampaignConfig(
        campaign_id="synthetic-robustness",
        samples=32,
        workers=workers,
        seed=4713,
        accepted_candidate_id="candidate-001",
        scalar_uncertainties=(
            ScalarUncertaintyConfig(
                name="injection.delta_a_m",
                distribution=DistributionKind.NORMAL,
                sigma=12.0,
            ),
            ScalarUncertaintyConfig(
                name="maneuver.timing_error_s",
                distribution=DistributionKind.UNIFORM,
                low=-2.0,
                high=3.0,
            ),
            ScalarUncertaintyConfig(
                name="window.unavailable",
                distribution=DistributionKind.BERNOULLI,
                probability_true=0.2,
            ),
        ),
        correlated_normal_groups=(
            CorrelatedNormalGroupConfig(
                group_id="od-roe",
                names=("od.delta_ex", "od.delta_ey"),
                covariance=((4.0e-8, 1.0e-8), (1.0e-8, 9.0e-8)),
            ),
        ),
        worst_metric="fleet.total_delta_v_m_s",
        worst_direction=WorstDirection.MAX,
        resume=resume,
    )


def _evaluator(sample: dict[str, object]) -> dict[str, object]:
    da = float(sample["injection.delta_a_m"])
    timing = float(sample["maneuver.timing_error_s"])
    ex = float(sample["od.delta_ex"])
    ey = float(sample["od.delta_ey"])
    unavailable = bool(sample["window.unavailable"])
    total_delta_v = abs(da) * 1.0e-4 + abs(timing) * 1.0e-3 + 10.0 * float(np.hypot(ex, ey))
    if unavailable:
        total_delta_v += 0.05
    return {
        "fleet": {
            "total_delta_v_m_s": total_delta_v,
            "residual_propellant_kg": 49.0 - total_delta_v,
        },
        "spacecraft": {"DEP": {"delta_v_m_s": total_delta_v}},
        "violations": {
            "window_unavailable": unavailable,
            "delta_v_limit": total_delta_v > 0.06,
        },
    }


def test_fixed_seed_samples_and_statistics_ignore_worker_count(tmp_path: Path) -> None:
    single_config = _config(1, resume=False)
    parallel_config = _config(4, resume=False)

    single_samples = generate_campaign_samples(single_config)
    parallel_samples = generate_campaign_samples(parallel_config)
    assert single_samples == parallel_samples

    single = run_robustness_campaign(single_config, _evaluator, tmp_path / "single", provenance={"backend": "test"})
    parallel = run_robustness_campaign(parallel_config, _evaluator, tmp_path / "parallel", provenance={"backend": "test"})

    assert single.samples == parallel.samples
    assert single.outcomes == parallel.outcomes
    assert single.summary == parallel.summary
    statistics = single.summary["statistics"]
    assert "fleet.total_delta_v_m_s" in statistics
    values = np.asarray([float(outcome["fleet"]["total_delta_v_m_s"]) for outcome in single.outcomes])
    assert statistics["fleet.total_delta_v_m_s"]["p50"] == float(np.percentile(values, 50))
    assert statistics["fleet.total_delta_v_m_s"]["p95"] == float(np.percentile(values, 95))
    assert statistics["fleet.total_delta_v_m_s"]["p99"] == float(np.percentile(values, 99))
    assert single.summary["worst_case"]["value"] == float(np.max(values))


def test_campaign_resume_reuses_completed_realizations(tmp_path: Path) -> None:
    config = _config(2, resume=True)
    calls = 0

    def counted(sample: dict[str, object]) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return _evaluator(sample)

    output = tmp_path / "resume"
    first = run_robustness_campaign(config, counted, output, provenance={"backend": "test"})
    assert calls == config.samples
    calls = 0
    second = run_robustness_campaign(config, counted, output, provenance={"backend": "test"})
    assert calls == 0
    assert first.samples == second.samples
    assert first.outcomes == second.outcomes
    assert first.summary == second.summary

    for name in (
        "campaign_manifest.json",
        "samples.parquet",
        "samples.csv",
        "outcomes.parquet",
        "outcomes.csv",
        "summary.json",
        "report.md",
        "report.html",
    ):
        assert (output / name).is_file()
    assert len(list((output / "realizations").glob("*/outcome.json"))) == config.samples
