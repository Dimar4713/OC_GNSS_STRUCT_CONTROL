from __future__ import annotations

from pathlib import Path

import numpy as np

from constellation_control.application.run import load_scenario
from constellation_control.control.campaign import run_closed_loop_campaign
from constellation_control.control.checkpoint import create_campaign_checkpoint
from constellation_control.control.execution import MPCExecutionPolicy, ManeuverAuthorityEvidence
from constellation_control.control.policies import CorrectionPolicy
from constellation_control.control.policy_execution import PolicyManeuverAttemptEvidence
from constellation_control.control.resume import resume_closed_loop_campaign
from constellation_control.control.transition import (
    AuthoritativeTransitionSnapshot,
    TransitionSpacecraftState,
)
from constellation_control.domain.models import Maneuver, OsculatingState, PropagationRequest, PropagationResult
from constellation_control.mean_elements.roe import RelativeOrbitalElements, mean_from_damico_roe


def _setup() -> tuple[PropagationRequest, object, float]:
    scenario = load_scenario(Path(__file__).parents[1] / "scenarios" / "mvp_45deg.yaml")
    constraints = scenario.constraints
    half_width = constraints.phase_corridor_rad
    reference = next(sat for sat in scenario.constellation.satellites if sat.role == "reference")
    deputy = next(sat for sat in scenario.constellation.satellites if sat.role == "additional")
    deputy = deputy.model_copy(
        update={
            "mean_orbit": mean_from_damico_roe(
                reference.mean_orbit,
                RelativeOrbitalElements(0.0, half_width, 0.0, 0.0, 0.0, 0.0),
            )
        }
    )
    return (
        PropagationRequest(
            scenario_id=scenario.scenario_id,
            epoch=scenario.epoch,
            frame=scenario.frame,
            time_scale=scenario.time_scale,
            satellites=(reference, deputy),
            maneuvers=(),
            duration_s=60.0,
            output_step_s=60.0,
            force_model=scenario.force_model,
            integrator=scenario.integrator,
            seed=scenario.seed,
        ),
        constraints,
        half_width,
    )


def _policy() -> MPCExecutionPolicy:
    return MPCExecutionPolicy(
        max_abs_impulse_rtn_m_s=(0.2, 0.2, 0.2),
        min_impulse_bit_m_s=1.0e-3,
        trust_tolerances_roe=(1.0e-6, 1.0e-3, 1.0e-6, 1.0e-6, 1.0e-6, 1.0e-6),
    )


def _cart(index: int, x_m: float) -> OsculatingState:
    return OsculatingState(epoch_s=float(index * 60), r_m=(x_m, 0.0, 0.0), v_m_s=(0.0, 0.0, 0.0))


def _coast(request: PropagationRequest, phases: tuple[float, ...]) -> PropagationResult:
    reference = next(sat for sat in request.satellites if sat.role == "reference")
    deputy = next(sat for sat in request.satellites if sat.role == "additional")
    times = tuple(float(i * 60) for i in range(len(phases)))
    return PropagationResult(
        backend="synthetic-coast",
        backend_version="test",
        force_model_fingerprint=request.force_model.fingerprint(),
        backend_metadata={},
        times_s=times,
        mean_orbits={
            reference.satellite_id: tuple(reference.mean_orbit for _ in phases),
            deputy.satellite_id: tuple(
                mean_from_damico_roe(
                    reference.mean_orbit,
                    RelativeOrbitalElements(0.0, phase, 0.0, 0.0, 0.0, 0.0),
                )
                for phase in phases
            ),
        },
        cartesian_states={
            reference.satellite_id: tuple(_cart(i, 0.0) for i in range(len(times))),
            deputy.satellite_id: tuple(_cart(i, 5000.0) for i in range(len(times))),
        },
    )


def _authorized(request: PropagationRequest, decision) -> PolicyManeuverAttemptEvidence:
    reference = next(sat for sat in request.satellites if sat.role == "reference")
    deputy = next(sat for sat in request.satellites if sat.role == "additional")
    remaining = deputy.spacecraft.propellant_mass_kg - 1.0
    maneuver = Maneuver(
        satellite_id=deputy.satellite_id,
        time_s=0.0,
        dv_rtn_m_s=(0.0, 0.03, 0.0),
    )
    authority = ManeuverAuthorityEvidence(
        authorized=True,
        reason="authorized-by-numerical-replay",
        deputy_id=deputy.satellite_id,
        reference_id=reference.satellite_id,
        first_maneuver=maneuver,
        predicted_next_roe=None,
        replay_next_roe=None,
        trust_error_ratio=0.1,
        replay_min_pair_distance_m=5000.0,
        propellant_used_kg=1.0,
        propellant_remaining_kg=remaining,
        required_reserve_kg=5.0,
        replay_backend="orekit-numerical-validation",
        replay_backend_metadata={},
        a_matrices=(),
        b_matrices=(),
        disturbances=(),
        mpc_states=(),
        mpc_impulses=(),
        mpc_objective=1.0,
    )
    transition = AuthoritativeTransitionSnapshot(
        continuation_sample_index=1,
        continuation_time_s=60.0,
        source_replay_times_s=(0.0, 60.0),
        controlled_satellite_id=deputy.satellite_id,
        reference_id=reference.satellite_id,
        spacecraft_states=tuple(
            TransitionSpacecraftState(
                satellite_id=sat.satellite_id,
                mean_orbit=sat.mean_orbit,
                cartesian_state=_cart(1, 0.0 if sat.role == "reference" else 5000.0),
            )
            for sat in request.satellites
        ),
        controlled_propellant_remaining_kg=remaining,
        controlled_total_mass_kg=deputy.spacecraft.dry_mass_kg + remaining,
        event_delta_v_m_s=0.03,
        event_propellant_used_kg=1.0,
        force_model_fingerprint=request.force_model.fingerprint(),
        backend="orekit-numerical-validation",
        backend_version="13.1.7",
        backend_metadata={},
        frame=request.frame,
        time_scale=request.time_scale,
        integrator=request.integrator,
    )
    return PolicyManeuverAttemptEvidence(decision, True, None, authority, transition)


def _pending_checkpoint(monkeypatch):
    request, constraints, half_width = _setup()
    calls: list[str] = []

    def fake_authorize(propagator, request, constraints, decision, base_policy, times_s, windows, *, deputy_id=None):
        del propagator, constraints, base_policy, times_s, windows, deputy_id
        calls.append("authority")
        return _authorized(request, decision)

    monkeypatch.setattr("constellation_control.control.campaign.authorize_policy_correction", fake_authorize)
    monkeypatch.setattr("constellation_control.control.resume.authorize_policy_correction", fake_authorize)

    class OneCoast:
        def __init__(self) -> None:
            self.calls = 0

        def propagate(self, coast_request: PropagationRequest) -> PropagationResult:
            self.calls += 1
            return _coast(coast_request, (half_width, 0.0, -half_width))

    first_prop = OneCoast()
    first = run_closed_loop_campaign(
        first_prop,
        request,
        constraints,
        CorrectionPolicy.BOUNDARY_TO_BOUNDARY,
        _policy(),
        np.asarray([0.0, 60.0]),
        np.asarray([True]),
        campaign_horizon_s=2000.0,
        coast_horizon_s=120.0,
        coast_output_step_s=60.0,
        max_corrections=1,
    )
    checkpoint = create_campaign_checkpoint(
        first,
        constraints=constraints,
        base_execution_policy=_policy(),
        campaign_horizon_s=2000.0,
        coast_horizon_s=120.0,
        coast_output_step_s=60.0,
        authority_times_s=np.asarray([0.0, 60.0]),
        maneuver_windows=np.asarray([True]),
        max_corrections=3,
        checkpoint_sequence=1,
    )
    calls.clear()
    return checkpoint, constraints, calls


def test_safe_stop_before_pending_authority_does_no_new_work(monkeypatch) -> None:
    checkpoint, _constraints, authority_calls = _pending_checkpoint(monkeypatch)

    class BombPropagator:
        def propagate(self, request):
            raise AssertionError("before-authority safe stop must not coast propagate")

    result = resume_closed_loop_campaign(
        BombPropagator(),
        checkpoint,
        safe_stop=lambda boundary: boundary.stage == "before-authority",
    )

    assert result.termination_reason == "operator-safe-stop"
    assert result.elapsed_time_s == checkpoint.elapsed_simulated_s
    assert result.resource_ledger == checkpoint.resource_ledger
    assert result.authority_attempts == checkpoint.authority_attempts
    assert authority_calls == []


def test_safe_stop_after_transition_is_atomic_and_checkpoint_has_no_pending_decision(monkeypatch) -> None:
    checkpoint, constraints, authority_calls = _pending_checkpoint(monkeypatch)

    class BombPropagator:
        def propagate(self, request):
            raise AssertionError("after-transition safe stop must happen before coast propagation")

    result = resume_closed_loop_campaign(
        BombPropagator(),
        checkpoint,
        safe_stop=lambda boundary: boundary.stage == "after-transition",
    )

    assert result.termination_reason == "operator-safe-stop"
    assert result.elapsed_time_s == checkpoint.elapsed_simulated_s + 60.0
    assert len(result.resource_ledger) == len(checkpoint.resource_ledger) + 1
    assert len(result.authority_attempts) == len(checkpoint.authority_attempts) + 1
    assert len(result.transitions) == len(checkpoint.transitions) + 1
    assert result.cumulative_delta_v_m_s == checkpoint.cumulative_delta_v_m_s + 0.03
    assert result.cumulative_propellant_used_kg == checkpoint.cumulative_propellant_used_kg + 1.0
    assert authority_calls == ["authority"]

    stopped_checkpoint = create_campaign_checkpoint(
        result,
        constraints=constraints,
        base_execution_policy=_policy(),
        campaign_horizon_s=2000.0,
        coast_horizon_s=120.0,
        coast_output_step_s=60.0,
        authority_times_s=np.asarray([0.0, 60.0]),
        maneuver_windows=np.asarray([True]),
        max_corrections=3,
        checkpoint_sequence=2,
    )
    assert stopped_checkpoint.pending_decision is None
    assert stopped_checkpoint.policy_armed is False
    assert stopped_checkpoint.checkpoint_sequence == 2
