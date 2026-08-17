from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from constellation_control.adapters.orekit.adapter import OrekitSidecarPropagator
from constellation_control.application.run import load_scenario
from constellation_control.control.execution import MPCExecutionPolicy, RecedingHorizonMPCController
from constellation_control.domain.models import Maneuver, PropagationRequest, ScenarioConfig


def _request_from_scenario(path: Path) -> tuple[PropagationRequest, ScenarioConfig]:
    scenario = load_scenario(path)
    request = PropagationRequest(
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
    return request, scenario


def _maneuver_payload(maneuver: Maneuver | None) -> dict[str, object] | None:
    return None if maneuver is None else maneuver.model_dump(mode="json")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    request, scenario = _request_from_scenario(args.scenario)
    sidecar_url = scenario.orekit_sidecar_url
    constraints = scenario.constraints
    if not sidecar_url:
        raise AssertionError("MPC authority acceptance requires orekit_sidecar_url")

    policy = MPCExecutionPolicy(
        max_abs_impulse_rtn_m_s=(0.15, 0.15, 0.15),
        min_impulse_bit_m_s=1.0e-6,
        trust_tolerances_roe=(5.0e-6, 3.0e-3, 3.0e-4, 3.0e-4, 3.0e-4, 3.0e-4),
        w_tracking=1.0e7,
        w_max=0.1,
    )
    propagator = OrekitSidecarPropagator(sidecar_url, timeout_s=300.0)
    controller = RecedingHorizonMPCController(
        propagator,
        policy,
        deputy_id="LIN-DEP",
        state_steps=np.asarray([2.0e-7, 2.0e-7, 1.0e-7, 1.0e-7, 1.0e-7, 1.0e-7]),
        impulse_step_m_s=1.0e-3,
    )
    times = np.asarray([0.0, request.duration_s], dtype=float)
    evidence = controller.authorize_first_maneuver(
        request,
        constraints,
        times,
        np.asarray([True]),
    )

    if not evidence.authorized:
        raise AssertionError(f"real Orekit MPC execution authority rejected smoke maneuver: {evidence.reason}")
    if evidence.first_maneuver is None:
        raise AssertionError("authorized MPC evidence omitted first maneuver")
    if evidence.first_maneuver.time_s != 0.0:
        raise AssertionError("receding-horizon authority may authorize only the first immediate maneuver")
    commanded = np.asarray(evidence.first_maneuver.dv_rtn_m_s, dtype=float)
    nonzero = np.abs(commanded) > 1.0e-10
    if not np.any(nonzero):
        raise AssertionError("MPC authority smoke did not produce a maneuver")
    if np.any(np.abs(commanded[nonzero]) < policy.min_impulse_bit_m_s):
        raise AssertionError("authorized maneuver violates minimum impulse bit")
    if evidence.replay_backend != "orekit-numerical-validation":
        raise AssertionError(f"unexpected replay backend: {evidence.replay_backend}")
    if evidence.replay_min_pair_distance_m is None or evidence.replay_min_pair_distance_m < constraints.min_pair_distance_m:
        raise AssertionError("authorized maneuver violates minimum-distance constraint")
    if evidence.trust_error_ratio is None or evidence.trust_error_ratio > 1.0:
        raise AssertionError(f"authorized maneuver exceeds linear-model trust region: {evidence.trust_error_ratio}")
    if evidence.propellant_remaining_kg < evidence.required_reserve_kg:
        raise AssertionError("authorized maneuver violates propellant reserve")
    if not evidence.requires_relinearization:
        raise AssertionError("receding-horizon evidence must require re-linearization before next decision")
    if len(evidence.a_matrices) != 1 or len(evidence.b_matrices) != 1 or len(evidence.disturbances) != 1:
        raise AssertionError("one-step MPC authority must preserve one A/B/d interval")

    metadata = evidence.replay_backend_metadata
    if metadata.get("gravity_model") != "EIGEN-6S":
        raise AssertionError("MPC authority replay lost EIGEN-6S identity")
    if metadata.get("orekit_version") != "13.1.7":
        raise AssertionError("MPC authority replay lost Orekit runtime version")
    for key in ("orekit_data_revision", "orekit_data_sha256"):
        if not metadata.get(key):
            raise AssertionError(f"MPC authority replay omitted {key}")

    payload = {
        "scenario_id": request.scenario_id,
        "force_model_fingerprint": request.force_model.fingerprint(),
        "policy": {
            "max_abs_impulse_rtn_m_s": list(policy.max_abs_impulse_rtn_m_s),
            "min_impulse_bit_m_s": policy.min_impulse_bit_m_s,
            "trust_tolerances_roe": list(policy.trust_tolerances_roe),
            "target_roe": list(policy.target_roe),
            "w_tracking": policy.w_tracking,
            "w_max": policy.w_max,
        },
        "authority": {
            "authorized": evidence.authorized,
            "reason": evidence.reason,
            "deputy_id": evidence.deputy_id,
            "reference_id": evidence.reference_id,
            "first_maneuver": _maneuver_payload(evidence.first_maneuver),
            "predicted_next_roe": evidence.predicted_next_roe,
            "replay_next_roe": evidence.replay_next_roe,
            "trust_error_ratio": evidence.trust_error_ratio,
            "replay_min_pair_distance_m": evidence.replay_min_pair_distance_m,
            "propellant_used_kg": evidence.propellant_used_kg,
            "propellant_remaining_kg": evidence.propellant_remaining_kg,
            "required_reserve_kg": evidence.required_reserve_kg,
            "replay_backend": evidence.replay_backend,
            "replay_backend_metadata": evidence.replay_backend_metadata,
            "requires_relinearization": evidence.requires_relinearization,
        },
        "A": evidence.a_matrices,
        "B": evidence.b_matrices,
        "d": evidence.disturbances,
        "mpc_states": evidence.mpc_states,
        "mpc_impulses": evidence.mpc_impulses,
        "mpc_objective": evidence.mpc_objective,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "mpc_execution_authority.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False),
        encoding="utf-8",
    )
    np.savez_compressed(
        args.output / "mpc_execution_authority.npz",
        A=np.asarray(evidence.a_matrices, dtype=float),
        B=np.asarray(evidence.b_matrices, dtype=float),
        d=np.asarray(evidence.disturbances, dtype=float),
        states=np.asarray(evidence.mpc_states, dtype=float),
        impulses=np.asarray(evidence.mpc_impulses, dtype=float),
    )
    print(
        json.dumps(
            {
                "authorized": evidence.authorized,
                "reason": evidence.reason,
                "dv_rtn_m_s": list(evidence.first_maneuver.dv_rtn_m_s),
                "trust_error_ratio": evidence.trust_error_ratio,
                "minimum_pair_distance_m": evidence.replay_min_pair_distance_m,
                "propellant_used_kg": evidence.propellant_used_kg,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
