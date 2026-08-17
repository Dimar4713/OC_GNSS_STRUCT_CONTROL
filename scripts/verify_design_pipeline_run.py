from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


REQUIRED = (
    "pipeline_manifest.json",
    "candidates.csv",
    "candidates.parquet",
    "pareto.csv",
    "pareto.parquet",
    "validation.json",
    "recommendation.json",
    "report.md",
    "report.html",
)


def verify(run_dir: Path, expected_data_revision: str) -> None:
    if not run_dir.is_dir():
        raise AssertionError(f"design run directory does not exist: {run_dir}")
    missing = [name for name in REQUIRED if not (run_dir / name).is_file()]
    if missing:
        raise AssertionError(f"missing design-pipeline artifacts: {missing}")
    empty = [name for name in REQUIRED if (run_dir / name).stat().st_size == 0]
    if empty:
        raise AssertionError(f"empty design-pipeline artifacts: {empty}")

    manifest = json.loads((run_dir / "pipeline_manifest.json").read_text(encoding="utf-8"))
    validation = json.loads((run_dir / "validation.json").read_text(encoding="utf-8"))
    recommendation = json.loads((run_dir / "recommendation.json").read_text(encoding="utf-8"))
    candidates = pd.read_csv(run_dir / "candidates.csv")
    pareto = pd.read_csv(run_dir / "pareto.csv")

    assert manifest["pipeline_config"]["recommendation"]["version"] == "weighted-normalized-v1"
    assert manifest["validation"]["gravity_model"] == "EIGEN-6S"
    assert "screening/design ranking cannot satisfy final acceptance" in manifest["authority_rule"]
    assert len(manifest["design_variable_names_per_spacecraft"]) == 6

    assert not candidates.empty
    assert not pareto.empty
    assert pareto["candidate_id"].is_unique
    assert set(pareto["candidate_id"]).issubset(set(candidates["candidate_id"]))

    assert len(validation) >= 1
    for item in validation:
        assert item["candidate_id"] in set(pareto["candidate_id"])
        assert item["backend"] == "orekit-numerical-validation"
        metadata = item["backend_metadata"]
        assert metadata["gravity_model"] == "EIGEN-6S"
        assert metadata["orekit_data_revision"] == expected_data_revision
        assert metadata["orekit_version"] == "13.1.7"
        assert len(metadata["orekit_data_sha256"]) == 64
        int(metadata["orekit_data_sha256"], 16)
        assert item["validation_metrics"]["minimum_pair_distance_m"] > 0.0

    recommended_id = recommendation["candidate"]["candidate_id"]
    assert recommended_id in set(pareto["candidate_id"])
    assert recommendation["policy_version"] == "weighted-normalized-v1"
    replay = recommendation["numerical_validation"]
    assert replay["candidate_id"] == recommended_id
    assert replay["backend"] == "orekit-numerical-validation"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--data-revision", required=True)
    args = parser.parse_args()
    verify(args.run_dir, args.data_revision)
    print(f"design-pipeline evidence OK: {args.run_dir}")


if __name__ == "__main__":
    main()
