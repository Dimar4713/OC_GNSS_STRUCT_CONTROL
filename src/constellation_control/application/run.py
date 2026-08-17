from __future__ import annotations

import json
import uuid
from importlib.metadata import PackageNotFoundError, version
from math import acos, pi, sqrt
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from constellation_control.adapters.orekit.adapter import OrekitSidecarPropagator
from constellation_control.adapters.synthetic.propagator import SyntheticMeanPropagator
from constellation_control.analysis.drift import default_harmonic_frequencies, harmonic_regression, linear_rate
from constellation_control.domain.models import (
    ExperimentRunManifest,
    ForceMode,
    PropagationRequest,
    ScenarioConfig,
    StabilityMetrics,
)
from constellation_control.domain.protocols import Propagator
from constellation_control.dynamics.j2 import first_order_j2_rates, mean_motion
from constellation_control.dynamics.orbits import mean_to_classical
from constellation_control.mean_elements.roe import damico_roe
from constellation_control.reporting.artifacts import write_run_artifacts


def load_scenario(path: Path) -> ScenarioConfig:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    scenario = ScenarioConfig.model_validate(payload)
    fingerprint = scenario.force_model.fingerprint()
    resolved_satellites = []
    for satellite in scenario.constellation.satellites:
        definition = satellite.mean_orbit.definition
        declared = definition.force_model_fingerprint
        if declared not in {"scenario", fingerprint}:
            raise ValueError(
                f"mean-element definition for {satellite.satellite_id} is bound to {declared}, "
                f"but scenario force model is {fingerprint}"
            )
        if declared == "scenario":
            definition = definition.model_copy(update={"force_model_fingerprint": fingerprint})
            mean_orbit = satellite.mean_orbit.model_copy(update={"definition": definition})
            satellite = satellite.model_copy(update={"mean_orbit": mean_orbit})
        resolved_satellites.append(satellite)
    constellation = scenario.constellation.model_copy(update={"satellites": tuple(resolved_satellites)})
    return scenario.model_copy(update={"constellation": constellation})


def _code_version() -> str:
    try:
        return version("constellation-control")
    except PackageNotFoundError:
        return "0.1.0+source"


def _ground_track_closure_error_m(
    r0: np.ndarray,
    r1: np.ndarray,
    duration_s: float,
    radius_m: float,
    omega: float,
) -> float:
    theta = omega * duration_s
    c, s = np.cos(theta), np.sin(theta)
    rotation = np.array([[c, s, 0.0], [-s, c, 0.0], [0.0, 0.0, 1.0]])
    u0 = r0 / np.linalg.norm(r0)
    u1 = rotation @ r1
    u1 = u1 / np.linalg.norm(u1)
    return radius_m * acos(float(np.clip(u0 @ u1, -1.0, 1.0)))


def run_scenario(scenario_path: Path, output_root: Path) -> Path:
    scenario = load_scenario(scenario_path)
    request = PropagationRequest(
        scenario_id=scenario.scenario_id,
        epoch=scenario.epoch,
        frame=scenario.frame,
        time_scale=scenario.time_scale,
        satellites=scenario.constellation.satellites,
        maneuvers=scenario.maneuvers,
        duration_s=scenario.duration_s,
        output_step_s=scenario.output_step_s,
        force_model=scenario.force_model,
        integrator=scenario.integrator,
        seed=scenario.seed,
    )
    propagator: Propagator
    if scenario.force_model.mode == ForceMode.SCREENING:
        propagator = SyntheticMeanPropagator()
    else:
        if not scenario.orekit_sidecar_url:
            raise RuntimeError(
                "design/validation modes require orekit_sidecar_url; no screening fallback is permitted"
            )
        propagator = OrekitSidecarPropagator(scenario.orekit_sidecar_url)

    result = propagator.propagate(request)
    times = np.asarray(result.times_s, dtype=float)
    satellite_by_id = {sat.satellite_id: sat for sat in scenario.constellation.satellites}
    metrics = []
    rows: list[dict[str, float | str]] = []

    for deputy in scenario.constellation.satellites:
        if deputy.role != "additional" or deputy.reference_id is None:
            continue
        reference = satellite_by_id[deputy.reference_id]
        ref_series = result.mean_orbits[reference.satellite_id]
        dep_series = result.mean_orbits[deputy.satellite_id]
        roes = [damico_roe(ref, dep) for ref, dep in zip(ref_series, dep_series, strict=True)]
        phase = np.asarray([roe.delta_lambda_rad for roe in roes])
        unwrapped_phase = np.unwrap(phase)
        initial_ref = mean_to_classical(reference.mean_orbit)
        orbital_period = 2.0 * pi / mean_motion(initial_ref.a_m, scenario.force_model.mu_m3_s2)
        fit = harmonic_regression(times, phase, default_harmonic_frequencies(orbital_period))

        ref_cart = result.cartesian_states[reference.satellite_id]
        dep_cart = result.cartesian_states[deputy.satellite_id]
        distances = np.asarray(
            [
                np.linalg.norm(np.asarray(dep.r_m) - np.asarray(ref.r_m))
                for ref, dep in zip(ref_cart, dep_cart, strict=True)
            ]
        )
        closest_index = int(np.argmin(distances))
        r0 = np.asarray(dep_cart[0].r_m)
        r1 = np.asarray(dep_cart[-1].r_m)
        closure = _ground_track_closure_error_m(
            r0,
            r1,
            times[-1] - times[0],
            scenario.force_model.reference_radius_m,
            scenario.force_model.earth_rotation_rate_rad_s,
        )
        ref_rates = first_order_j2_rates(initial_ref, scenario.force_model)
        dep_rates = first_order_j2_rates(mean_to_classical(deputy.mean_orbit), scenario.force_model)
        ex_rate = sqrt(
            linear_rate(times, np.asarray([roe.delta_ex for roe in roes])) ** 2
            + linear_rate(times, np.asarray([roe.delta_ey for roe in roes])) ** 2
        )
        ix_rate = sqrt(
            linear_rate(times, np.asarray([roe.delta_ix for roe in roes])) ** 2
            + linear_rate(times, np.asarray([roe.delta_iy for roe in roes])) ** 2
        )
        pair_id = f"{deputy.satellite_id}/{reference.satellite_id}"
        metric = StabilityMetrics(
            pair_id=pair_id,
            secular_drift_delta_lambda_rad_s=fit.secular_drift_rad_s,
            periodic_amplitude_delta_lambda_rad=fit.periodic_amplitude_rad,
            secular_drift_raan_rad_s=dep_rates.raan_rad_s - ref_rates.raan_rad_s,
            eccentricity_vector_drift_rate_s=ex_rate,
            inclination_vector_drift_rate_s=ix_rate,
            minimum_pair_distance_m=float(distances[closest_index]),
            time_of_closest_approach_s=float(times[closest_index]),
            ground_track_closure_error_m=float(closure),
            pdop=None,
        )
        metrics.append(metric)
        for index, (time_s, roe) in enumerate(zip(times, roes, strict=True)):
            rows.append(
                {
                    "pair_id": pair_id,
                    "time_s": float(time_s),
                    "delta_lambda_rad": float(unwrapped_phase[index]),
                    "trend_rad": float(fit.trend_rad[index]),
                    "harmonic_rad": float(fit.harmonic_rad[index]),
                    "delta_a_mean_m": float(dep_series[index].a_m - ref_series[index].a_m),
                    "delta_ex": roe.delta_ex,
                    "delta_ey": roe.delta_ey,
                    "delta_ix": roe.delta_ix,
                    "delta_iy": roe.delta_iy,
                    "pair_distance_m": float(distances[index]),
                }
            )

    config_hash = scenario.config_hash()
    run_id = str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"{scenario.scenario_id}:{config_hash}:{scenario.seed}:{_code_version()}",
        )
    )
    manifest = ExperimentRunManifest(
        scenario_id=scenario.scenario_id,
        run_id=run_id,
        config_hash=config_hash,
        code_version=_code_version(),
        force_model_fingerprint=scenario.force_model.fingerprint(),
        force_model_mode=scenario.force_model.mode,
        force_model=scenario.force_model,
        integrator=scenario.integrator,
        constraints=scenario.constraints,
        frame=scenario.frame,
        time_scale=scenario.time_scale,
        mean_element_definitions={
            sat.satellite_id: sat.mean_orbit.definition for sat in scenario.constellation.satellites
        },
        backend=result.backend,
        backend_version=result.backend_version,
        backend_metadata=result.backend_metadata,
        epoch=scenario.epoch,
        random_seed=scenario.seed,
        algorithm_versions={
            "drift": "harmonic-lstsq-v1",
            "roe": "damico-v1",
            "screening": "j2-first-order-v1",
        },
    )
    summary = {
        "metrics": [metric.model_dump(mode="json") for metric in metrics],
        "constraints": scenario.constraints.model_dump(mode="json"),
        "provenance": {
            "epoch": scenario.epoch.isoformat(),
            "frame": scenario.frame.value,
            "time_scale": scenario.time_scale.value,
            "gravity_degree": scenario.force_model.gravity_degree,
            "gravity_order": scenario.force_model.gravity_order,
            "integrator": scenario.integrator.model_dump(mode="json"),
            "backend_metadata": result.backend_metadata,
            "maneuver_count": len(scenario.maneuvers),
        },
        "mean_element_rule": (
            "all secular drift metrics use force-model-consistent mean elements; osculating a is excluded"
        ),
    }
    run_dir = output_root / scenario.scenario_id / run_id
    write_run_artifacts(run_dir, manifest, summary, pd.DataFrame(rows))
    (run_dir / "scenario.normalized.json").write_text(
        json.dumps(scenario.model_dump(mode="json"), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return run_dir
