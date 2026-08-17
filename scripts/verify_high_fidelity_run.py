from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


BASE_REQUIRED_ARTIFACTS = (
    "manifest.json",
    "summary.json",
    "scenario.normalized.json",
    "timeseries.csv",
    "timeseries.parquet",
    "ground_track.csv",
    "ground_track.parquet",
    "resources.csv",
    "resources.parquet",
    "report.md",
    "report.html",
    "01_delta_lambda.png",
    "02_delta_a_mean.png",
    "03_eccentricity_vector.png",
    "04_inclination_vector.png",
    "05_minimum_distance.png",
    "06_delta_raan.png",
    "07_ground_track.png",
    "09_maneuver_delta_v.png",
    "10_propellant_reserve.png",
    "interactive_delta_lambda.html",
)

VALIDATION_GEOMETRY_ARTIFACTS = (
    "navigation_geometry.csv",
    "navigation_geometry.parquet",
    "08_navigation_pdop.png",
)


def verify_run(
    run_dir: Path,
    expected_backend: str,
    expected_mode: str,
    expected_data_revision: str,
) -> None:
    if not run_dir.is_dir():
        raise AssertionError(f"run directory does not exist: {run_dir}")

    required = BASE_REQUIRED_ARTIFACTS + (
        VALIDATION_GEOMETRY_ARTIFACTS if expected_mode == "validation" else ()
    )
    missing = [name for name in required if not (run_dir / name).is_file()]
    if missing:
        raise AssertionError(f"missing high-fidelity artifacts: {missing}")

    empty = [name for name in required if (run_dir / name).stat().st_size == 0]
    if empty:
        raise AssertionError(f"empty high-fidelity artifacts: {empty}")

    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    scenario = json.loads((run_dir / "scenario.normalized.json").read_text(encoding="utf-8"))

    assert manifest["backend"] == expected_backend
    assert manifest["backend_version"] == "13.1.7"
    assert manifest["force_model_mode"] == expected_mode
    assert manifest["frame"] == "EME2000"
    assert manifest["time_scale"] == "UTC"
    assert manifest["force_model"]["gravity_model"] == "EIGEN-6S"
    assert manifest["force_model"]["gravity_degree"] == 8
    assert manifest["force_model"]["gravity_order"] == 8

    metadata = manifest["backend_metadata"]
    assert metadata["orekit_version"] == "13.1.7"
    assert metadata["gravity_model"] == "EIGEN-6S"
    assert metadata["orekit_data_revision"] == expected_data_revision
    assert len(metadata["orekit_data_sha256"]) == 64
    int(metadata["orekit_data_sha256"], 16)
    assert metadata["gravity_degree"] == "8"
    assert metadata["gravity_order"] == "8"
    assert metadata["frame"] == "EME2000"
    assert metadata["time_scale"] == "UTC"

    fingerprint = manifest["force_model_fingerprint"]
    assert len(fingerprint) == 64
    int(fingerprint, 16)
    for definition in manifest["mean_element_definitions"].values():
        assert definition["force_model_fingerprint"] == fingerprint

    assert scenario["force_model"]["mode"] == expected_mode
    assert scenario["force_model"]["gravity_model"] == "EIGEN-6S"
    assert scenario["force_model"]["gravity_degree"] == 8
    assert scenario["force_model"]["gravity_order"] == 8
    assert scenario["force_model"]["moon"] is True
    assert scenario["force_model"]["sun"] is True
    assert scenario["force_model"]["srp"] is True
    assert scenario["force_model"]["relativity"] is False
    assert scenario["force_model"]["tides"] is False

    metrics = summary.get("metrics", [])
    if len(metrics) != 1:
        raise AssertionError(f"expected one synthetic additional/reference metric, got {len(metrics)}")
    metric = metrics[0]
    assert metric["pair_id"] == "SYNTH-ADD-45/SYNTH-REF"
    assert metric["minimum_pair_distance_m"] > 0.0

    provenance = summary["provenance"]
    assert provenance["backend_metadata"]["gravity_model"] == "EIGEN-6S"
    assert provenance["backend_metadata"]["orekit_data_revision"] == expected_data_revision
    assert provenance["gravity_degree"] == 8
    assert provenance["gravity_order"] == 8
    assert provenance["ground_track_transform"] == "simple-earth-rotation-z-v1 + geocentric-subpoint-v1"

    ground_track = pd.read_parquet(run_dir / "ground_track.parquet")
    assert set(ground_track["satellite_id"]) == {"SYNTH-REF", "SYNTH-ADD-45"}
    assert ground_track["closure_from_initial_m"].ge(0.0).all()

    resources = pd.read_parquet(run_dir / "resources.parquet")
    assert set(resources["satellite_id"]) == {"SYNTH-REF", "SYNTH-ADD-45"}
    assert resources["cumulative_delta_v_m_s"].ge(0.0).all()
    assert resources["residual_propellant_kg"].ge(resources["required_reserve_kg"]).all()

    if expected_mode == "validation":
        geometry = pd.read_parquet(run_dir / "navigation_geometry.parquet")
        assert set(geometry["site_id"]) == {"SYNTH-EQUATOR-0"}
        assert len(geometry) > 0
        assert geometry["visible_count"].between(0, 2).all()
        assert not geometry["available"].astype(bool).any()
        assert geometry["pdop"].isna().all()
        assert set(geometry["unavailable_reason"].dropna()) <= {
            "fewer-than-four-visible-satellites",
            "rank-deficient-geometry",
        }
        navigation = summary["navigation_geometry"]
        assert navigation["requested"] is True
        site_summary = navigation["sites"]["SYNTH-EQUATOR-0"]
        assert site_summary["available_samples"] == 0
        assert site_summary["pdop"] is None
        assert metric["pdop"] is None
        assert provenance["navigation_geometry_transform"] == (
            "simple-earth-rotation-z-v1 + ellipsoid-site-ecef + local-enu-v1"
        )
        assert scenario["navigation_sites"][0]["site_id"] == "SYNTH-EQUATOR-0"

        ten_static_plots = [run_dir / f"{index:02d}_" for index in range(1, 11)]
        for prefix in ten_static_plots:
            matches = list(run_dir.glob(prefix.name + "*.png"))
            if len(matches) != 1 or matches[0].stat().st_size == 0:
                raise AssertionError(f"expected exactly one retained static plot for prefix {prefix.name}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--backend", required=True)
    parser.add_argument("--mode", choices=("design", "validation"), required=True)
    parser.add_argument("--data-revision", required=True)
    args = parser.parse_args()
    verify_run(args.run_dir, args.backend, args.mode, args.data_revision)
    print(f"high-fidelity evidence OK: {args.run_dir}")


if __name__ == "__main__":
    main()
