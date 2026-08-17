from __future__ import annotations

import hashlib
import html
import json
from importlib.metadata import PackageNotFoundError, version
from math import hypot, pi, sqrt
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from constellation_control.adapters.orekit.adapter import OrekitSidecarPropagator
from constellation_control.adapters.synthetic.propagator import SyntheticMeanPropagator
from constellation_control.analysis.drift import default_harmonic_frequencies, harmonic_regression
from constellation_control.application.run import load_scenario
from constellation_control.domain.models import ForceMode, PropagationRequest, PropagationResult, ScenarioConfig
from constellation_control.domain.protocols import Propagator
from constellation_control.dynamics.j2 import mean_motion
from constellation_control.mean_elements.roe import damico_roe
from constellation_control.optimization.pipeline import (
    CandidateEvaluation,
    CandidateRecord,
    DesignPipelineConfig,
    DesignPipelineResult,
    run_design_pipeline,
)
from constellation_control.optimization.validation import ValidationOutcome


DESIGN_VARIABLE_NAMES = ("delta_a_m", "delta_ex", "delta_ey", "delta_ix", "delta_iy", "delta_lambda_rad")


def _code_version() -> str:
    try:
        return version("constellation-control")
    except PackageNotFoundError:
        return "0.1.0+source"


def load_design_pipeline_config(path: Path) -> DesignPipelineConfig:
    return DesignPipelineConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def _additional_satellites(scenario: ScenarioConfig) -> tuple[str, ...]:
    return tuple(sat.satellite_id for sat in scenario.constellation.satellites if sat.role == "additional")


def _validate_scenario_pair(screening: ScenarioConfig, validation: ScenarioConfig, config: DesignPipelineConfig) -> None:
    if screening.force_model.mode != ForceMode.SCREENING:
        raise ValueError("design pipeline screening scenario must use screening force mode")
    if validation.force_model.mode != ForceMode.VALIDATION:
        raise ValueError("design pipeline final scenario must use validation force mode")
    if not validation.orekit_sidecar_url:
        raise ValueError("design pipeline validation scenario requires orekit_sidecar_url")
    if screening.epoch != validation.epoch or screening.frame != validation.frame or screening.time_scale != validation.time_scale:
        raise ValueError("screening and validation scenarios must share epoch, frame and time scale")
    screening_map = {
        sat.satellite_id: (sat.role, sat.reference_id, sat.plane_id) for sat in screening.constellation.satellites
    }
    validation_map = {
        sat.satellite_id: (sat.role, sat.reference_id, sat.plane_id) for sat in validation.constellation.satellites
    }
    if screening_map != validation_map:
        raise ValueError("screening and validation scenarios must share constellation identity/reference topology")
    additional = _additional_satellites(screening)
    if len(config.bounds) != 6 * len(additional):
        raise ValueError("design bounds must contain exactly six variables per additional spacecraft")
    if screening.maneuvers or validation.maneuvers:
        raise ValueError("design search baseline scenarios must not contain maneuvers")


def apply_design_vector(scenario: ScenarioConfig, vector: np.ndarray) -> ScenarioConfig:
    values = np.asarray(vector, dtype=float)
    additional = [sat for sat in scenario.constellation.satellites if sat.role == "additional"]
    if values.shape != (6 * len(additional),):
        raise ValueError("design vector length does not match additional-spacecraft count")
    by_id = {sat.satellite_id: sat for sat in scenario.constellation.satellites}
    replacements = {}
    for index, deputy in enumerate(additional):
        if deputy.reference_id is None:
            raise ValueError("additional spacecraft is missing reference_id")
        reference = by_id[deputy.reference_id]
        da, dex, dey, dix, diy, dlambda = values[6 * index : 6 * (index + 1)]
        ref = reference.mean_orbit
        mean_orbit = deputy.mean_orbit.model_copy(
            update={
                "a_m": ref.a_m + float(da),
                "ex": ref.ex + float(dex),
                "ey": ref.ey + float(dey),
                "ix": ref.ix + float(dix),
                "iy": ref.iy + float(diy),
                "lambda_rad": ref.lambda_rad + float(dlambda),
            }
        )
        replacements[deputy.satellite_id] = deputy.model_copy(update={"mean_orbit": mean_orbit})
    satellites = tuple(replacements.get(sat.satellite_id, sat) for sat in scenario.constellation.satellites)
    return scenario.model_copy(update={"constellation": scenario.constellation.model_copy(update={"satellites": satellites})})


def _request(scenario: ScenarioConfig) -> PropagationRequest:
    return PropagationRequest(
        scenario_id=scenario.scenario_id,
        epoch=scenario.epoch,
        frame=scenario.frame,
        time_scale=scenario.time_scale,
        satellites=scenario.constellation.satellites,
        maneuvers=(),
        duration_s=scenario.duration_s,
        output_step_s=scenario.output_step_s,
        force_model=scenario.force_model,
        integrator=scenario.integrator,
        seed=scenario.seed,
    )


def _evaluate_result(scenario: ScenarioConfig, vector: np.ndarray, result: PropagationResult) -> CandidateEvaluation:
    times = np.asarray(result.times_s, dtype=float)
    by_id = {sat.satellite_id: sat for sat in scenario.constellation.satellites}
    additional = [sat for sat in scenario.constellation.satellites if sat.role == "additional"]
    maximum_phase_envelope = 0.0
    minimum_pair_distance = float("inf")
    delta_v_proxy = 0.0
    margins: list[float] = []

    for index, deputy in enumerate(additional):
        if deputy.reference_id is None:
            raise ValueError("additional spacecraft is missing reference_id")
        reference = by_id[deputy.reference_id]
        ref_series = result.mean_orbits[reference.satellite_id]
        dep_series = result.mean_orbits[deputy.satellite_id]
        roes = [damico_roe(ref, dep) for ref, dep in zip(ref_series, dep_series, strict=True)]
        phase = np.asarray([roe.delta_lambda_rad for roe in roes], dtype=float)
        orbital_period = 2.0 * pi / mean_motion(reference.mean_orbit.a_m, scenario.force_model.mu_m3_s2)
        fit = harmonic_regression(times, phase, default_harmonic_frequencies(orbital_period))
        phase_envelope = abs(fit.secular_drift_rad_s) * scenario.duration_s + fit.periodic_amplitude_rad
        maximum_phase_envelope = max(maximum_phase_envelope, float(phase_envelope))

        ref_cart = result.cartesian_states[reference.satellite_id]
        dep_cart = result.cartesian_states[deputy.satellite_id]
        pair_minimum = min(
            float(np.linalg.norm(np.asarray(dep.r_m) - np.asarray(ref.r_m)))
            for ref, dep in zip(ref_cart, dep_cart, strict=True)
        )
        minimum_pair_distance = min(minimum_pair_distance, pair_minimum)

        da, dex, dey, dix, diy, dlambda = vector[6 * index : 6 * (index + 1)]
        lower_da, upper_da = scenario.constraints.delta_a_bounds_m
        margins.extend(
            (
                float(da - lower_da),
                float(upper_da - da),
                float(scenario.constraints.delta_e_max - hypot(float(dex), float(dey))),
                float(scenario.constraints.delta_i_max_rad - hypot(float(dix), float(diy))),
                float(scenario.constraints.phase_corridor_rad - abs(float(dlambda))),
            )
        )
        circular_speed = sqrt(scenario.force_model.mu_m3_s2 / reference.mean_orbit.a_m)
        delta_v_proxy += circular_speed * (
            abs(float(da)) / (2.0 * reference.mean_orbit.a_m)
            + hypot(float(dex), float(dey))
            + hypot(float(dix), float(diy))
        )

    if not np.isfinite(minimum_pair_distance):
        raise ValueError("design pipeline requires at least one additional/reference pair")
    margins.append(float(minimum_pair_distance - scenario.constraints.min_pair_distance_m))
    return CandidateEvaluation(
        objectives=(
            float(maximum_phase_envelope),
            float(delta_v_proxy),
            float(-minimum_pair_distance),
        ),
        constraint_margins=tuple(margins),
        metrics={
            "phase_envelope_rad": float(maximum_phase_envelope),
            "design_delta_v_proxy_m_s": float(delta_v_proxy),
            "minimum_pair_distance_m": float(minimum_pair_distance),
        },
    )


def _propagate_and_evaluate(
    base_scenario: ScenarioConfig,
    vector: np.ndarray,
    propagator: Propagator,
) -> tuple[PropagationResult, CandidateEvaluation]:
    scenario = apply_design_vector(base_scenario, vector)
    result = propagator.propagate(_request(scenario))
    return result, _evaluate_result(scenario, vector, result)


def _record_dict(record: CandidateRecord) -> dict[str, object]:
    payload: dict[str, object] = {
        "candidate_id": record.candidate_id,
        "stage": record.stage,
        "feasible": record.feasible,
        "parent_candidate_id": record.parent_candidate_id,
    }
    for index, value in enumerate(record.vector):
        payload[f"x{index}"] = value
    for index, value in enumerate(record.objectives):
        payload[f"objective_{index}"] = value
    for index, value in enumerate(record.constraint_margins):
        payload[f"constraint_margin_{index}"] = value
    payload.update(record.metrics)
    return payload


def _write_design_artifacts(
    output_dir: Path,
    result: DesignPipelineResult,
    config: DesignPipelineConfig,
    screening: ScenarioConfig,
    validation: ScenarioConfig,
    validation_provenance: dict[tuple[float, ...], dict[str, str]],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    records = pd.DataFrame([_record_dict(record) for record in result.records])
    records.to_csv(output_dir / "candidates.csv", index=False)
    records.to_parquet(output_dir / "candidates.parquet", index=False)
    pareto = records[records["candidate_id"].isin(result.pareto_candidate_ids)].copy()
    pareto.to_csv(output_dir / "pareto.csv", index=False)
    pareto.to_parquet(output_dir / "pareto.parquet", index=False)

    pareto_records = {
        record.vector: record for record in result.records if record.candidate_id in result.pareto_candidate_ids
    }
    validation_rows = []
    for evidence in result.validation:
        vector = tuple(evidence.design_vector)
        record = pareto_records.get(vector)
        if record is None:
            raise RuntimeError("validation evidence lost candidate lineage")
        validation_rows.append(
            {
                "candidate_id": record.candidate_id,
                "candidate_index": evidence.candidate_index,
                "design_vector": list(evidence.design_vector),
                "design_objectives": list(evidence.design_objectives),
                "ranking_score": evidence.ranking_score,
                "backend": evidence.backend,
                "validation_metrics": evidence.validation_metrics,
                "backend_metadata": validation_provenance[vector],
            }
        )
    (output_dir / "validation.json").write_text(json.dumps(validation_rows, indent=2, sort_keys=True), encoding="utf-8")

    recommendation = next(
        record for record in result.records if record.candidate_id == result.recommendation_candidate_id
    )
    recommendation_validation = next(
        (item for item in validation_rows if item["candidate_id"] == recommendation.candidate_id),
        None,
    )
    if recommendation_validation is None:
        raise RuntimeError("recommended Pareto candidate lacks authoritative numerical validation")
    (output_dir / "recommendation.json").write_text(
        json.dumps(
            {
                "policy_version": result.policy_version,
                "candidate": _record_dict(recommendation),
                "numerical_validation": recommendation_validation,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    manifest = {
        "code_version": _code_version(),
        "pipeline_config": config.model_dump(mode="json"),
        "screening": {
            "scenario_id": screening.scenario_id,
            "config_hash": screening.config_hash(),
            "force_model_fingerprint": screening.force_model.fingerprint(),
            "backend": "synthetic-j2-screening",
        },
        "validation": {
            "scenario_id": validation.scenario_id,
            "config_hash": validation.config_hash(),
            "force_model_fingerprint": validation.force_model.fingerprint(),
            "gravity_model": validation.force_model.gravity_model.value if validation.force_model.gravity_model else None,
        },
        "authority_rule": "screening/design ranking cannot satisfy final acceptance; recommendation requires orekit-numerical replay",
        "design_variable_names_per_spacecraft": DESIGN_VARIABLE_NAMES,
    }
    (output_dir / "pipeline_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    markdown = "\n".join(
        (
            "# Constellation design pipeline",
            "",
            f"- Recommendation policy: `{result.policy_version}`",
            f"- Pareto candidates: `{len(result.pareto_candidate_ids)}`",
            f"- Recommended candidate: `{result.recommendation_candidate_id}`",
            f"- Numerical validation replays: `{len(result.validation)}`",
            "",
            "The recommendation is valid only because the selected candidate has authoritative numerical Orekit replay evidence.",
        )
    ) + "\n"
    (output_dir / "report.md").write_text(markdown, encoding="utf-8")
    (output_dir / "report.html").write_text(
        f"<html><body><pre>{html.escape(markdown)}</pre></body></html>",
        encoding="utf-8",
    )


def run_design_application(
    screening_scenario_path: Path,
    validation_scenario_path: Path,
    pipeline_config_path: Path,
    output_root: Path,
) -> Path:
    screening = load_scenario(screening_scenario_path)
    validation = load_scenario(validation_scenario_path)
    config = load_design_pipeline_config(pipeline_config_path)
    _validate_scenario_pair(screening, validation, config)

    screening_propagator = SyntheticMeanPropagator()
    validation_propagator = OrekitSidecarPropagator(validation.orekit_sidecar_url or "")
    validation_provenance: dict[tuple[float, ...], dict[str, str]] = {}

    def evaluator(vector: np.ndarray) -> CandidateEvaluation:
        _, evaluation = _propagate_and_evaluate(screening, vector, screening_propagator)
        return evaluation

    def validator(vector: np.ndarray) -> ValidationOutcome:
        propagated, evaluation = _propagate_and_evaluate(validation, vector, validation_propagator)
        if not propagated.backend.lower().startswith("orekit-numerical"):
            raise RuntimeError(f"final design validation requires numerical Orekit, got {propagated.backend}")
        metadata = dict(sorted(propagated.backend_metadata.items()))
        required = ("orekit_version", "orekit_data_revision", "orekit_data_sha256", "gravity_model")
        if any(not metadata.get(key) for key in required):
            raise RuntimeError("numerical Orekit validation omitted required authority provenance")
        validation_provenance[tuple(float(value) for value in vector)] = metadata
        return ValidationOutcome(backend=propagated.backend, metrics=evaluation.metrics)

    result = run_design_pipeline(config, evaluator=evaluator, validator=validator)
    run_payload = {
        "screening_hash": screening.config_hash(),
        "validation_hash": validation.config_hash(),
        "pipeline": config.model_dump(mode="json"),
        "code_version": _code_version(),
    }
    run_hash = hashlib.sha256(
        json.dumps(run_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:20]
    output_dir = output_root / f"{screening.scenario_id}--design" / run_hash
    _write_design_artifacts(output_dir, result, config, screening, validation, validation_provenance)
    return output_dir
