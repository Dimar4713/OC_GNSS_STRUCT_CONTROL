from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from constellation_control.adapters.orekit.adapter import OrekitSidecarPropagator
from constellation_control.application.run import load_scenario
from constellation_control.control.linearization import FiniteDifferenceRoeLinearizationProvider
from constellation_control.domain.models import PropagationRequest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    scenario = load_scenario(args.scenario)
    if not scenario.orekit_sidecar_url:
        raise AssertionError("linearization smoke requires orekit_sidecar_url")

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
    propagator = OrekitSidecarPropagator(scenario.orekit_sidecar_url, timeout_s=300.0)
    provider = FiniteDifferenceRoeLinearizationProvider(
        propagator,
        deputy_id="LIN-DEP",
        state_steps=np.asarray([2e-7, 2e-7, 1e-7, 1e-7, 1e-7, 1e-7]),
        impulse_step_m_s=1e-3,
    )
    times = np.asarray([0.0, scenario.duration_s], dtype=float)
    a_matrices, b_matrices, disturbances = provider.linearize(request, times)

    assert a_matrices.shape == (1, 6, 6)
    assert b_matrices.shape == (1, 6, 3)
    assert disturbances.shape == (1, 6)
    assert np.all(np.isfinite(a_matrices))
    assert np.all(np.isfinite(b_matrices))
    assert np.all(np.isfinite(disturbances))

    diagonal = np.diag(a_matrices[0])
    if not np.all(np.abs(diagonal - 1.0) < 0.15):
        raise AssertionError(f"unexpected local-state diagonal: {diagonal}")

    # A positive along-track impulse must increase deputy mean semi-major axis,
    # hence normalized D'Amico delta-a. This is the key physical sign check for B.
    tangential_delta_a = float(b_matrices[0, 0, 1])
    if tangential_delta_a <= 0.0:
        raise AssertionError(f"positive tangential impulse produced B[delta_a,T]={tangential_delta_a}")

    eccentricity_response = float(np.linalg.norm(b_matrices[0, 2:4, 0:2]))
    inclination_response = float(np.linalg.norm(b_matrices[0, 4:6, 2]))
    if eccentricity_response <= 1e-8:
        raise AssertionError("RT impulse columns do not produce a measurable eccentricity-vector response")
    if inclination_response <= 1e-8:
        raise AssertionError("normal impulse column does not produce a measurable inclination-vector response")

    args.output.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        args.output / "orekit_roe_linearization.npz",
        A=a_matrices,
        B=b_matrices,
        d=disturbances,
        times_s=times,
    )
    evidence = {
        "scenario_id": scenario.scenario_id,
        "force_model_fingerprint": scenario.force_model.fingerprint(),
        "gravity_model": scenario.force_model.gravity_model.value if scenario.force_model.gravity_model else None,
        "state_steps": provider._state_steps.tolist(),  # noqa: SLF001 - test evidence records actual perturbations
        "impulse_step_m_s": provider._impulse_step_m_s,  # noqa: SLF001
        "A": a_matrices.tolist(),
        "B": b_matrices.tolist(),
        "d": disturbances.tolist(),
        "checks": {
            "tangential_delta_a": tangential_delta_a,
            "eccentricity_response": eccentricity_response,
            "inclination_response": inclination_response,
        },
    }
    (args.output / "orekit_roe_linearization.json").write_text(
        json.dumps(evidence, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(evidence["checks"], sort_keys=True))


if __name__ == "__main__":
    main()
