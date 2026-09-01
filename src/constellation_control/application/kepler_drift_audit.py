from __future__ import annotations

import html
import json
from dataclasses import asdict
from math import pi
from pathlib import Path

import numpy as np
import pandas as pd

from constellation_control.analysis.drift import default_harmonic_frequencies, harmonic_regression
from constellation_control.analysis.kepler_drift_consistency import (
    KeplerDriftConsistency,
    analyze_kepler_drift_consistency,
)
from constellation_control.analysis.relative_operations import relative_mean_phase_series_rad
from constellation_control.domain.models import ExperimentRunManifest, PropagationResult, ScenarioConfig
from constellation_control.dynamics.j2 import mean_motion
from constellation_control.dynamics.orbits import wrap_pi
from constellation_control.reporting.artifacts import _engineering_report

AUDIT_VERSION = "mean-a-kepler-baseline-v1"


def enrich_run_with_kepler_drift_audit(run_dir: Path) -> tuple[KeplerDriftConsistency, ...]:
    """Add an independent central-field drift baseline to an already completed run.

    This auditor deliberately runs after propagation and reads persisted authoritative
    mean-element results. It never feeds back into the propagator, controller, force
    model, or existing operational metrics.
    """

    scenario_path = run_dir / "scenario.normalized.json"
    result_path = run_dir / "propagation_result.json"
    summary_path = run_dir / "summary.json"
    manifest_path = run_dir / "manifest.json"
    timeseries_path = run_dir / "timeseries.csv"
    required = (scenario_path, result_path, summary_path, manifest_path, timeseries_path)
    missing = [path.name for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError(f"completed-run Kepler audit is missing artifacts: {', '.join(missing)}")

    scenario = ScenarioConfig.model_validate(json.loads(scenario_path.read_text(encoding="utf-8")))
    result = PropagationResult.model_validate_json(result_path.read_text(encoding="utf-8"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if not isinstance(summary, dict):
        raise ValueError("run summary must be a JSON object")
    manifest = ExperimentRunManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    timeseries = pd.read_csv(timeseries_path)

    satellite_by_id = {satellite.satellite_id: satellite for satellite in scenario.constellation.satellites}
    relative_by_pair: dict[str, dict[str, object]] = {}
    raw_relatives = summary.get("relative_operations", [])
    if isinstance(raw_relatives, list):
        for item in raw_relatives:
            if isinstance(item, dict) and isinstance(item.get("pair_id"), str):
                relative_by_pair[str(item["pair_id"])] = item

    times = np.asarray(result.times_s, dtype=float)
    audit_rows: list[dict[str, object]] = []
    diagnostics: list[KeplerDriftConsistency] = []

    for deputy in scenario.constellation.satellites:
        if deputy.role != "additional" or deputy.reference_id is None:
            continue
        reference = satellite_by_id[deputy.reference_id]
        pair_id = f"{deputy.satellite_id}/{reference.satellite_id}"
        ref_series = result.mean_orbits[reference.satellite_id]
        dep_series = result.mean_orbits[deputy.satellite_id]
        if len(ref_series) != times.size or len(dep_series) != times.size:
            raise ValueError(f"mean history length mismatch for pair {pair_id}")

        delta_lambda = np.unwrap(
            np.asarray(
                [
                    wrap_pi(dep.lambda_rad - ref.lambda_rad)
                    for ref, dep in zip(ref_series, dep_series, strict=True)
                ],
                dtype=float,
            )
        )
        delta_u = relative_mean_phase_series_rad(ref_series, dep_series)
        reference_period = 2.0 * pi / mean_motion(ref_series[0].a_m, scenario.force_model.mu_m3_s2)
        frequencies = default_harmonic_frequencies(reference_period)
        lambda_fit = harmonic_regression(times, delta_lambda, frequencies)
        u_fit = harmonic_regression(times, delta_u, frequencies)

        diagnostic, delta_n = analyze_kepler_drift_consistency(
            ref_series,
            dep_series,
            mu_m3_s2=scenario.force_model.mu_m3_s2,
            measured_delta_lambda_rate_rad_s=lambda_fit.secular_drift_rad_s,
            measured_delta_u_rate_rad_s=u_fit.secular_drift_rad_s,
        )
        diagnostics.append(diagnostic)
        payload = {"pair_id": pair_id, **asdict(diagnostic)}
        audit_rows.append(payload)

        relative = relative_by_pair.get(pair_id)
        if relative is not None:
            relative["kepler_drift_consistency"] = asdict(diagnostic)

        mask = timeseries["pair_id"].astype(str) == pair_id
        pair_times = timeseries.loc[mask, "time_s"].to_numpy(dtype=float)
        if pair_times.size != times.size or not np.allclose(pair_times, times, rtol=0.0, atol=1.0e-9):
            raise ValueError(f"timeseries evidence does not align with propagation times for pair {pair_id}")
        timeseries.loc[mask, "kepler_delta_n_rad_s"] = delta_n
        timeseries.loc[mask, "kepler_delta_n_deg_day"] = np.degrees(delta_n) * 86400.0
        timeseries.loc[mask, "kepler_time_mean_delta_n_deg_day"] = diagnostic.time_mean_kepler_delta_n_deg_day
        timeseries.loc[mask, "measured_delta_lambda_harmonic_rate_deg_day"] = diagnostic.measured_delta_lambda_rate_deg_day
        timeseries.loc[mask, "measured_delta_u_harmonic_rate_deg_day"] = diagnostic.measured_delta_u_rate_deg_day
        timeseries.loc[mask, "delta_lambda_minus_kepler_deg_day"] = diagnostic.delta_lambda_minus_kepler_deg_day
        timeseries.loc[mask, "delta_u_minus_kepler_deg_day"] = diagnostic.delta_u_minus_kepler_deg_day

    summary["kepler_drift_consistency"] = audit_rows
    provenance = summary.setdefault("provenance", {})
    if isinstance(provenance, dict):
        provenance["kepler_drift_consistency"] = {
            "version": AUDIT_VERSION,
            "input": "persisted force-model-consistent mean elements + scenario mu",
            "central_field_formula": "n=sqrt(mu/a_mean^3); T=2*pi/n; Delta_n=n_deputy-n_reference",
            "authority": "independent diagnostic only; does not modify propagation or operational metrics",
        }

    algorithm_versions = dict(manifest.algorithm_versions)
    algorithm_versions["kepler_drift_consistency"] = AUDIT_VERSION
    manifest = manifest.model_copy(update={"algorithm_versions": algorithm_versions})

    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    timeseries.to_csv(timeseries_path, index=False)
    timeseries.to_parquet(run_dir / "timeseries.parquet", index=False)
    (run_dir / "kepler_drift_consistency.json").write_text(
        json.dumps(audit_rows, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    audit_markdown = _audit_report(audit_rows)
    (run_dir / "kepler_drift_consistency.md").write_text(audit_markdown, encoding="utf-8")
    (run_dir / "kepler_drift_consistency.html").write_text(
        f"<html><body><pre>{html.escape(audit_markdown)}</pre></body></html>",
        encoding="utf-8",
    )
    engineering_markdown = _engineering_report(manifest, summary)
    (run_dir / "report.md").write_text(engineering_markdown, encoding="utf-8")
    (run_dir / "report.html").write_text(
        f"<html><body><pre>{html.escape(engineering_markdown)}</pre></body></html>",
        encoding="utf-8",
    )
    return tuple(diagnostics)


def _audit_report(rows: list[dict[str, object]]) -> str:
    lines = [
        "# Independent Kepler-vs-measured drift consistency",
        "",
        "This is a central-field baseline derived from persisted force-model-consistent mean semi-major axes.",
        "It does not replace the Orekit/DSST metrics. Full-force Delta lambda and Delta u=lambda-Omega may differ",
        "because node/perigee dynamics and non-Kepler perturbations contribute to the measured rates.",
        "",
        "| Pair | Delta T initial, s | Kepler Delta n, deg/day | Measured Delta lambda, deg/day | Measured Delta u, deg/day |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    if not rows:
        lines.append("| no additional/reference pair | - | - | - | - |")
    for row in rows:
        lines.append(
            "| {pair_id} | {initial_period_difference_s} | {time_mean_kepler_delta_n_deg_day} | "
            "{measured_delta_lambda_rate_deg_day} | {measured_delta_u_rate_deg_day} |".format(**row)
        )
    lines.extend(
        [
            "",
            "Hand-check formula: `Delta lambda_dot_K = 360*86400*(1/T_deputy - 1/T_reference)` deg/day.",
            "The sign convention is deputy minus reference.",
            "",
        ]
    )
    return "\n".join(lines)
