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
from constellation_control.analysis.drift import (
    DEFAULT_HARMONIC_LABELS,
    default_harmonic_frequencies,
    harmonic_regression,
    linear_rate,
)
from constellation_control.analysis.fuel import propellant_used_kg
from constellation_control.analysis.kepler_consistency import (
    angular_rate_deg_day,
    kepler_drift_consistency_summary,
    kepler_relative_drift_baseline,
)
from constellation_control.analysis.navigation_geometry import evaluate_navigation_geometry, inertial_to_ecef_m
from constellation_control.analysis.relative_operations import (
    analyze_relative_operations,
    forecast_phase_corridor,
)
from constellation_control.application.propellant_state import (
    build_maneuver_resource_rows,
    resolve_operational_satellites,
)
from constellation_control.domain.models import (
    ExperimentRunManifest,
    ForceMode,
    PropagationRequest,
    PropagationResult,
    ScenarioConfig,
    StabilityMetrics,
)
from constellation_control.domain.protocols import Propagator
from constellation_control.dynamics.j2 import mean_motion
from constellation_control.dynamics.orbits import mean_to_classical, wrap_pi
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


def _build_ground_track(scenario: ScenarioConfig, result: PropagationResult) -> pd.DataFrame:
    rows: list[dict[str, float | str]] = []
    radius = scenario.force_model.reference_radius_m
    omega = scenario.force_model.earth_rotation_rate_rad_s
    for satellite_id in sorted(result.cartesian_states):
        states = result.cartesian_states[satellite_id]
        initial_ecef: np.ndarray | None = None
        for time_s, state in zip(result.times_s, states, strict=True):
            ecef = inertial_to_ecef_m(
                state.r_m,
                time_s=float(time_s),
                earth_rotation_rate_rad_s=omega,
            )
            if initial_ecef is None:
                initial_ecef = ecef
            norm = float(np.linalg.norm(ecef))
            if norm <= 0.0:
                raise RuntimeError("ground-track state has zero position norm")
            longitude = float(np.arctan2(ecef[1], ecef[0]))
            latitude = float(np.arctan2(ecef[2], np.hypot(ecef[0], ecef[1])))
            u0 = initial_ecef / np.linalg.norm(initial_ecef)
            u = ecef / norm
            closure = radius * acos(float(np.clip(u0 @ u, -1.0, 1.0)))
            rows.append(
                {
                    "satellite_id": satellite_id,
                    "time_s": float(time_s),
                    "ecef_x_m": float(ecef[0]),
                    "ecef_y_m": float(ecef[1]),
                    "ecef_z_m": float(ecef[2]),
                    "longitude_rad": longitude,
                    "geocentric_latitude_rad": latitude,
                    "closure_from_initial_m": float(closure),
                }
            )
    return pd.DataFrame(rows)


def _build_navigation_geometry(
    scenario: ScenarioConfig,
    result: PropagationResult,
) -> pd.DataFrame | None:
    if not scenario.navigation_sites:
        return None
    rows: list[dict[str, object]] = []
    satellite_ids = tuple(sorted(result.cartesian_states))
    for index, time_s in enumerate(result.times_s):
        positions = {
            satellite_id: result.cartesian_states[satellite_id][index].r_m
            for satellite_id in satellite_ids
        }
        for site in scenario.navigation_sites:
            metrics = evaluate_navigation_geometry(
                positions,
                time_s=float(time_s),
                site=site,
                reference_radius_m=scenario.force_model.reference_radius_m,
                flattening=scenario.force_model.flattening,
                earth_rotation_rate_rad_s=scenario.force_model.earth_rotation_rate_rad_s,
            )
            rows.append(
                {
                    "site_id": site.site_id,
                    "time_s": float(time_s),
                    "available": metrics.available,
                    "visible_count": len(metrics.visible_satellite_ids),
                    "visible_satellite_ids": ";".join(metrics.visible_satellite_ids),
                    "gdop": metrics.gdop,
                    "pdop": metrics.pdop,
                    "hdop": metrics.hdop,
                    "vdop": metrics.vdop,
                    "unavailable_reason": metrics.reason,
                }
            )
    return pd.DataFrame(rows)


def _navigation_summary(frame: pd.DataFrame | None) -> dict[str, object]:
    if frame is None:
        return {"requested": False, "transform": "not-requested", "sites": {}}
    sites: dict[str, object] = {}
    for site_id, site_frame in frame.groupby("site_id", sort=True):
        finite_pdop = site_frame["pdop"].dropna().astype(float)
        statistics: dict[str, float | int] | None
        if finite_pdop.empty:
            statistics = None
        else:
            values = finite_pdop.to_numpy(dtype=float)
            statistics = {
                "count": int(values.size),
                "p50": float(np.percentile(values, 50)),
                "p95": float(np.percentile(values, 95)),
                "p99": float(np.percentile(values, 99)),
                "worst": float(np.max(values)),
            }
        sites[str(site_id)] = {
            "samples": int(len(site_frame)),
            "available_samples": int(site_frame["available"].astype(bool).sum()),
            "availability_fraction": float(site_frame["available"].astype(bool).mean()),
            "pdop": statistics,
        }
    return {
        "requested": True,
        "transform": "simple-earth-rotation-z-v1 + ellipsoid-site-ecef + local-enu-v1",
        "sites": sites,
    }


def _representative_pdop(frame: pd.DataFrame | None) -> float | None:
    if frame is None:
        return None
    finite = frame["pdop"].dropna().astype(float)
    if finite.empty:
        return None
    return float(finite.max())


def _resource_row(
    scenario: ScenarioConfig,
    satellite_id: str,
    initial_mass_kg: float,
    propellant_mass_kg: float,
    isp_s: float,
    reserve_kg: float,
    time_s: float,
    cumulative_delta_v_m_s: float,
) -> dict[str, float | str]:
    used = propellant_used_kg(initial_mass_kg, cumulative_delta_v_m_s, isp_s)
    return {
        "satellite_id": satellite_id,
        "time_s": float(time_s),
        "cumulative_delta_v_m_s": float(cumulative_delta_v_m_s),
        "propellant_used_kg": float(used),
        "residual_propellant_kg": float(propellant_mass_kg - used),
        "required_reserve_kg": float(reserve_kg),
    }


def _build_resource_history(scenario: ScenarioConfig) -> pd.DataFrame:
    rows: list[dict[str, float | str]] = []
    for satellite in scenario.constellation.satellites:
        spacecraft = satellite.spacecraft
        maneuvers = sorted(
            (item for item in scenario.maneuvers if item.satellite_id == satellite.satellite_id),
            key=lambda item: item.time_s,
        )
        reserve = spacecraft.propellant_mass_kg * scenario.constraints.propellant_reserve_fraction
        cumulative_delta_v = 0.0
        rows.append(
            _resource_row(
                scenario,
                satellite.satellite_id,
                spacecraft.initial_mass_kg,
                spacecraft.propellant_mass_kg,
                spacecraft.isp_s,
                reserve,
                0.0,
                cumulative_delta_v,
            )
        )
        for maneuver in maneuvers:
            cumulative_delta_v += float(np.linalg.norm(np.asarray(maneuver.dv_rtn_m_s, dtype=float)))
            rows.append(
                _resource_row(
                    scenario,
                    satellite.satellite_id,
                    spacecraft.initial_mass_kg,
                    spacecraft.propellant_mass_kg,
                    spacecraft.isp_s,
                    reserve,
                    maneuver.time_s,
                    cumulative_delta_v,
                )
            )
        if scenario.duration_s > 0.0 and (not maneuvers or maneuvers[-1].time_s != scenario.duration_s):
            rows.append(
                _resource_row(
                    scenario,
                    satellite.satellite_id,
                    spacecraft.initial_mass_kg,
                    spacecraft.propellant_mass_kg,
                    spacecraft.isp_s,
                    reserve,
                    scenario.duration_s,
                    cumulative_delta_v,
                )
            )
    return pd.DataFrame(rows)


def run_scenario(scenario_path: Path, output_root: Path) -> Path:
    scenario = load_scenario(scenario_path)
    resources = pd.DataFrame(build_maneuver_resource_rows(scenario))
    operational_satellites = resolve_operational_satellites(scenario)
    request = PropagationRequest(
        scenario_id=scenario.scenario_id,
        epoch=scenario.epoch,
        frame=scenario.frame,
        time_scale=scenario.time_scale,
        satellites=operational_satellites,
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
    ground_track = _build_ground_track(scenario, result)
    navigation_geometry = _build_navigation_geometry(scenario, result)
    navigation_summary = _navigation_summary(navigation_geometry)
    representative_pdop = _representative_pdop(navigation_geometry)

    satellite_by_id = {sat.satellite_id: sat for sat in scenario.constellation.satellites}
    metrics = []
    relative_operations: list[dict[str, object]] = []
    kepler_consistency_diagnostics: list[dict[str, object]] = []
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

        ref_classical = [mean_to_classical(item) for item in ref_series]
        dep_classical = [mean_to_classical(item) for item in dep_series]
        initial_ref = ref_classical[0]
        orbital_period = 2.0 * pi / mean_motion(initial_ref.a_m, scenario.force_model.mu_m3_s2)
        frequencies = default_harmonic_frequencies(orbital_period)
        phase_fit = harmonic_regression(times, phase, frequencies)
        delta_raan = np.unwrap(
            np.asarray(
                [
                    wrap_pi(dep.raan_rad - ref.raan_rad)
                    for ref, dep in zip(ref_classical, dep_classical, strict=True)
                ]
            )
        )
        raan_fit = harmonic_regression(times, delta_raan, frequencies)
        operations, delta_u, along_track = analyze_relative_operations(times, ref_series, dep_series)
        delta_u_fit = harmonic_regression(times, delta_u, frequencies)
        ref_a_mean = np.asarray([item.a_m for item in ref_series], dtype=float)
        dep_a_mean = np.asarray([item.a_m for item in dep_series], dtype=float)
        kepler_baseline = kepler_relative_drift_baseline(
            times,
            ref_a_mean,
            dep_a_mean,
            scenario.force_model.mu_m3_s2,
        )
        kepler_consistency = kepler_drift_consistency_summary(
            kepler_baseline,
            mu_m3_s2=scenario.force_model.mu_m3_s2,
            measured_delta_lambda_rad_s=phase_fit.secular_drift_rad_s,
            measured_delta_u_rad_s=delta_u_fit.secular_drift_rad_s,
        )
        corridor = forecast_phase_corridor(
            current_delta_u_rad=float(delta_u[-1]),
            secular_delta_u_rate_rad_s=operations.secular_delta_u_rate_rad_s,
            half_width_rad=scenario.constraints.phase_corridor_rad,
        )

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
            secular_drift_delta_lambda_rad_s=phase_fit.secular_drift_rad_s,
            periodic_amplitude_delta_lambda_rad=phase_fit.periodic_amplitude_rad,
            secular_drift_raan_rad_s=raan_fit.secular_drift_rad_s,
            eccentricity_vector_drift_rate_s=ex_rate,
            inclination_vector_drift_rate_s=ix_rate,
            minimum_pair_distance_m=float(distances[closest_index]),
            time_of_closest_approach_s=float(times[closest_index]),
            ground_track_closure_error_m=float(closure),
            pdop=representative_pdop,
        )
        metrics.append(metric)
        pair_kepler_consistency = {
            "pair_id": pair_id,
            "reference_id": reference.satellite_id,
            "deputy_id": deputy.satellite_id,
            **kepler_consistency,
        }
        kepler_consistency_diagnostics.append(pair_kepler_consistency)
        periodic_components = [
            {
                "basis": label,
                "period_s": component.period_s,
                "period_days": component.period_s / 86400.0,
                "amplitude_rad": component.amplitude_rad,
                "amplitude_deg": float(np.degrees(component.amplitude_rad)),
                "peak_to_peak_rad": component.peak_to_peak_rad,
                "peak_to_peak_deg": float(np.degrees(component.peak_to_peak_rad)),
            }
            for label, component in zip(DEFAULT_HARMONIC_LABELS, delta_u_fit.components, strict=True)
        ]
        relative_operations.append(
            {
                "pair_id": pair_id,
                "reference_id": reference.satellite_id,
                "deputy_id": deputy.satellite_id,
                "phase_coordinate": "u_mean=lambda-Omega",
                "phase_semantics": "mean phase M+omega; not osculating argument of latitude",
                "along_track_semantics": "near-circular mean arc proxy a_ref*Delta_u; not Cartesian separation",
                "phase_corridor_semantics": "symmetric +/- constraints.phase_corridor_rad around Delta_u=0",
                "phase_corridor": corridor.__dict__,
                "kepler_drift_consistency": kepler_consistency,
                "periodic_delta_u": {
                    "basis": "orbital + sidereal_day + lunar + sidereal_year",
                    "components": periodic_components,
                    "rss_component_amplitude_rad": delta_u_fit.periodic_amplitude_rad,
                    "rss_component_amplitude_deg": float(np.degrees(delta_u_fit.periodic_amplitude_rad)),
                    "rss_semantics": (
                        "root-sum-square of fitted component amplitudes; not a single harmonic amplitude and has no single period"
                    ),
                    "component_semantics": "amplitude is center-to-peak; peak_to_peak is exactly 2*amplitude",
                },
                **operations.__dict__,
            }
        )
        corridor_deg = float(np.degrees(scenario.constraints.phase_corridor_rad))
        measured_lambda_rate = phase_fit.secular_drift_rad_s
        measured_u_rate = delta_u_fit.secular_drift_rad_s
        lambda_residual = measured_lambda_rate - kepler_baseline.time_mean_delta_n_rad_s
        u_residual = measured_u_rate - kepler_baseline.time_mean_delta_n_rad_s
        for index, (time_s, roe) in enumerate(zip(times, roes, strict=True)):
            rows.append(
                {
                    "pair_id": pair_id,
                    "time_s": float(time_s),
                    "delta_lambda_rad": float(unwrapped_phase[index]),
                    "trend_rad": float(phase_fit.trend_rad[index]),
                    "harmonic_rad": float(phase_fit.harmonic_rad[index]),
                    "delta_u_mean_rad": float(delta_u[index]),
                    "delta_u_mean_deg": float(np.degrees(delta_u[index])),
                    "delta_u_trend_rad": float(delta_u_fit.trend_rad[index]),
                    "delta_u_harmonic_rad": float(delta_u_fit.harmonic_rad[index]),
                    "delta_u_harmonic_deg": float(np.degrees(delta_u_fit.harmonic_rad[index])),
                    "secular_delta_u_rate_rad_s": operations.secular_delta_u_rate_rad_s,
                    "secular_delta_u_rate_deg_day": operations.secular_delta_u_rate_deg_day,
                    "secular_along_track_proxy_rate_m_s": operations.secular_along_track_proxy_rate_m_s,
                    "phase_corridor_upper_deg": corridor_deg,
                    "phase_corridor_lower_deg": -corridor_deg,
                    "along_track_mean_arc_proxy_m": float(along_track[index]),
                    "reference_a_mean_m": float(kepler_baseline.reference_a_mean_m[index]),
                    "deputy_a_mean_m": float(kepler_baseline.deputy_a_mean_m[index]),
                    "delta_a_mean_m": float(dep_series[index].a_m - ref_series[index].a_m),
                    "reference_kepler_period_s": float(kepler_baseline.reference_period_s[index]),
                    "deputy_kepler_period_s": float(kepler_baseline.deputy_period_s[index]),
                    "kepler_period_difference_s": float(kepler_baseline.period_difference_s[index]),
                    "reference_kepler_mean_motion_rad_s": float(
                        kepler_baseline.reference_mean_motion_rad_s[index]
                    ),
                    "deputy_kepler_mean_motion_rad_s": float(
                        kepler_baseline.deputy_mean_motion_rad_s[index]
                    ),
                    "kepler_delta_n_rad_s": float(kepler_baseline.delta_n_rad_s[index]),
                    "kepler_delta_n_deg_day": angular_rate_deg_day(
                        float(kepler_baseline.delta_n_rad_s[index])
                    ),
                    "measured_harmonic_delta_lambda_rad_s": measured_lambda_rate,
                    "measured_harmonic_delta_lambda_deg_day": angular_rate_deg_day(
                        measured_lambda_rate
                    ),
                    "measured_harmonic_delta_u_rad_s": measured_u_rate,
                    "measured_harmonic_delta_u_deg_day": angular_rate_deg_day(measured_u_rate),
                    "delta_lambda_minus_kepler_residual_rad_s": lambda_residual,
                    "delta_lambda_minus_kepler_residual_deg_day": angular_rate_deg_day(lambda_residual),
                    "delta_u_minus_kepler_residual_rad_s": u_residual,
                    "delta_u_minus_kepler_residual_deg_day": angular_rate_deg_day(u_residual),
                    "delta_ex": roe.delta_ex,
                    "delta_ey": roe.delta_ey,
                    "delta_ix": roe.delta_ix,
                    "delta_iy": roe.delta_iy,
                    "delta_raan_rad": float(delta_raan[index]),
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
            "phase_drift": "harmonic-lstsq-v1",
            "raan_drift": "harmonic-lstsq-v1",
            "relative_mean_phase": "u-mean-lambda-minus-raan-v1",
            "relative_phase_periodic": "harmonic-lstsq-default-basis-v1",
            "kepler_relative_drift_consistency": "mean-a-central-field-v1",
            "along_track_proxy": "mean-arc-a-delta-u-v1",
            "phase_corridor_forecast": "linear-secular-rate-v1",
            "roe": "damico-v1",
            "screening": "j2-first-order-v1",
            "navigation_geometry": "ellipsoid-ecef-enu-dop-v1",
            "earth_fixed_reporting": "simple-earth-rotation-z-v1",
            "resource_accounting": "operational-sequential-tsiolkovsky-v2",
        },
    )
    summary = {
        "metrics": [metric.model_dump(mode="json") for metric in metrics],
        "relative_operations": relative_operations,
        "kepler_drift_consistency": kepler_consistency_diagnostics,
        "constraints": scenario.constraints.model_dump(mode="json"),
        "navigation_geometry": navigation_summary,
        "provenance": {
            "epoch": scenario.epoch.isoformat(),
            "frame": scenario.frame.value,
            "time_scale": scenario.time_scale.value,
            "gravity_degree": scenario.force_model.gravity_degree,
            "gravity_order": scenario.force_model.gravity_order,
            "integrator": scenario.integrator.model_dump(mode="json"),
            "backend_metadata": result.backend_metadata,
            "maneuver_count": len(scenario.maneuvers),
            "navigation_sites": [site.model_dump(mode="json") for site in scenario.navigation_sites],
            "navigation_geometry_transform": (
                "simple-earth-rotation-z-v1 + ellipsoid-site-ecef + local-enu-v1"
            ),
            "ground_track_transform": "simple-earth-rotation-z-v1 + geocentric-subpoint-v1",
        },
        "mean_element_rule": (
            "all secular drift metrics use force-model-consistent mean elements; osculating a is excluded"
        ),
    }
    run_dir = output_root / scenario.scenario_id / run_id
    write_run_artifacts(
        run_dir,
        manifest,
        summary,
        pd.DataFrame(rows),
        ground_track=ground_track,
        navigation_geometry=navigation_geometry,
        resources=resources,
    )
    (run_dir / "scenario.normalized.json").write_text(
        json.dumps(scenario.model_dump(mode="json"), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (run_dir / "propagation_result.json").write_text(
        result.model_dump_json(indent=2),
        encoding="utf-8",
    )
    return run_dir