from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


REQUIRED = (
    "campaign_manifest.json",
    "samples.csv",
    "samples.parquet",
    "outcomes.csv",
    "outcomes.parquet",
    "statistics.csv",
    "violation_probability.csv",
    "summary.json",
    "report.md",
    "report.html",
)
EXPECTED_VIOLATIONS = {
    "minimum_pair_distance",
    "phase_corridor",
    "delta_a_corridor",
    "eccentricity_corridor",
    "inclination_corridor",
    "propellant_reserve",
    "maneuver_window_unavailable",
}
DATA_REVISION = "baf158744d38ec76cf94e2d396280d545b9f0ba2"
DATA_SHA = "7c0387b0bf7f08f0393b724090c9b926870cae4dde1d02823d57291eab0a3fcf"


def verify(run_dir: Path) -> None:
    if not run_dir.is_dir():
        raise AssertionError(f"robustness run directory does not exist: {run_dir}")
    missing = [name for name in REQUIRED if not (run_dir / name).is_file()]
    if missing:
        raise AssertionError(f"missing robustness artifacts: {missing}")
    empty = [name for name in REQUIRED if (run_dir / name).stat().st_size == 0]
    if empty:
        raise AssertionError(f"empty robustness artifacts: {empty}")

    manifest = json.loads((run_dir / "campaign_manifest.json").read_text(encoding="utf-8"))
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    samples = pd.read_parquet(run_dir / "samples.parquet")
    outcomes = pd.read_parquet(run_dir / "outcomes.parquet")
    statistics = pd.read_csv(run_dir / "statistics.csv")
    violation_table = pd.read_csv(run_dir / "violation_probability.csv")

    config = manifest["config"]
    provenance = manifest["provenance"]
    assert manifest["campaign_id"] == "synthetic-high-fidelity-robustness-smoke"
    assert len(manifest["campaign_config_hash"]) == 64
    int(manifest["campaign_config_hash"], 16)
    assert config["samples"] == 6
    assert config["workers"] == 2
    assert config["seed"] == 4713
    assert config["accepted_candidate_id"] == "synthetic-mpc-authority-smoke"
    assert provenance["accepted_candidate_id"] == config["accepted_candidate_id"]
    assert provenance["required_backend_prefix"] == "orekit-numerical"
    assert provenance["required_orekit_version"] == "13.1.7"
    assert provenance["required_gravity_model"] == "EIGEN-6S"
    assert provenance["required_orekit_data_revision"] == DATA_REVISION
    assert provenance["required_orekit_data_sha256"] == DATA_SHA
    assert len(provenance["force_model_fingerprint"]) == 64
    int(provenance["force_model_fingerprint"], 16)

    assert len(samples) == 6
    assert samples["realization"].tolist() == list(range(6))
    assert samples["sample_sha256"].is_unique
    assert samples["sample_sha256"].map(lambda value: len(str(value)) == 64).all()
    for required_source in (
        "initial.LIN-DEP.delta_a_m",
        "slot.LIN-DEP.delta_lambda_rad",
        "od.LIN-DEP.delta_a_m",
        "od.LIN-DEP.delta_ex",
        "maneuver.0.magnitude_fraction",
        "maneuver.0.direction_r_rad",
        "maneuver.0.timing_error_s",
        "spacecraft.LIN-DEP.cr_area_over_mass_fraction",
        "window.0.unavailable",
    ):
        assert required_source in samples.columns

    assert len(outcomes) == 6
    decoded: list[dict[str, object]] = [json.loads(value) for value in outcomes["outcome_json"]]
    total_delta_v: list[float] = []
    for realization, outcome in enumerate(decoded):
        assert outcome["backend"] == "orekit-numerical-validation"
        metadata = outcome["backend_metadata"]
        assert metadata["orekit_version"] == "13.1.7"
        assert metadata["gravity_model"] == "EIGEN-6S"
        assert metadata["orekit_data_revision"] == DATA_REVISION
        assert metadata["orekit_data_sha256"] == DATA_SHA
        violations = outcome["violations"]
        assert set(violations) == EXPECTED_VIOLATIONS
        assert all(isinstance(value, bool) for value in violations.values())
        fleet = outcome["fleet"]
        spacecraft = outcome["spacecraft"]
        dep = spacecraft["LIN-DEP"]
        assert fleet["minimum_pair_distance_m"] > 0.0
        assert dep["residual_propellant_kg"] <= 50.0
        assert dep["required_reserve_kg"] == 5.0
        assert fleet["total_delta_v_m_s"] >= 0.0
        total_delta_v.append(float(fleet["total_delta_v_m_s"]))
        realization_dir = run_dir / "realizations" / f"{realization:06d}"
        assert (realization_dir / "sample.json").is_file()
        assert (realization_dir / "outcome.json").is_file()

    stats = summary["statistics"]
    for metric in (
        "fleet.total_delta_v_m_s",
        "fleet.total_propellant_used_kg",
        "fleet.minimum_pair_distance_m",
        "spacecraft.LIN-DEP.delta_v_m_s",
        "spacecraft.LIN-DEP.residual_propellant_kg",
    ):
        assert metric in stats
        assert stats[metric]["count"] == 6
        assert stats[metric]["p50"] <= stats[metric]["p95"] <= stats[metric]["p99"]
    lifetime_key = "spacecraft.LIN-DEP.reserve_lifetime_estimate_s"
    assert lifetime_key in stats
    assert 1 <= stats[lifetime_key]["count"] <= 6

    values = np.asarray(total_delta_v, dtype=float)
    delta_v_stats = stats["fleet.total_delta_v_m_s"]
    assert delta_v_stats["p50"] == float(np.percentile(values, 50))
    assert delta_v_stats["p95"] == float(np.percentile(values, 95))
    assert delta_v_stats["p99"] == float(np.percentile(values, 99))
    assert delta_v_stats["worst"] == float(np.max(values))
    assert summary["worst_case"]["realization"] == int(np.argmax(values))
    assert summary["worst_case"]["value"] == float(np.max(values))

    probabilities = summary["violation_probability"]
    assert set(probabilities) == EXPECTED_VIOLATIONS
    assert all(0.0 <= float(value) <= 1.0 for value in probabilities.values())
    assert set(statistics["metric"]) >= set(stats)
    assert set(violation_table["name"]) == EXPECTED_VIOLATIONS

    report = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "Metric distributions" in report
    assert "Constraint / event probabilities" in report
    assert "synthetic-mpc-authority-smoke" in report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    verify(args.run_dir)
    print(f"robustness evidence OK: {args.run_dir}")


if __name__ == "__main__":
    main()
