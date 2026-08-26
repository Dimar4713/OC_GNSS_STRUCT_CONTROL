from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

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


def _request_at_delta_u(delta_u_rad: float) -> tuple[PropagationRequest, object]:
    scenario = load_scenario(Path(__file__).parents[1] / "scenarios" / "mvp_45deg.yaml")
    reference = next(sat for sat in scenario.constellation.satellites if sat.role == "reference")
    deputy = next(sat for sat in scenario.constellation.satellites if sat.role == "additional")
    deputy = deputy.model_copy(
        update={
            "mean_orbit": mean_from_damico_roe(
                reference.mean_orbit,
                RelativeOrbitalElements(0.0, delta_u_rad, 0.0, 0.0, 0.0, 0.0),
            )
        }
    )
    request = PropagationRequest(
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
    )
    return request, scenario.constraints


def _execution_policy() -> MPCExecutionPolicy:
    return MPCExecutionPolicy(
        max_abs_impulse_rtn_m_s=(0.2, 0.2, 0.2),
        min_impulse_bit_m_s=1.0e-3,
        trust_tolerances_roe=(1.0e-6, 1.0e-3, 1.0e-6, 1.0e-6, 1.0e-6, 1.0e-6),
    )


def _cartesian(index: int, x_m: float) -> OsculatingState:
    return OsculatingState(
        epoch_s=float(index * 60),
        r_m=(x_m, 0.0, 0.0),
        v_m_s=(0.0, 0.0, 0.0),
    )


def _coast_result(request: PropagationRequest, phases: tuple[float, ...]) -> PropagationResult:
    reference = next(sat for sat in request.satellites if sat.role == "reference")
    deputy = next(sat for sat in request.satellites if sat.role == "additional")
    ref_history = tuple(reference.mean_orbit for _ in phases)
    dep_history = tuple(
        mean_from_damico_roe(
            reference.mean_orbit,
            RelativeOrbitalElements(0.0, phase, 0.0, 0.0, 0.0, 0.0),
        )
        for phase in phases
    )
    times = tuple(float(index * 60) for index in range(len(phases)))
    return PropagationResult(
        backend="synthetic-coast",
        backend_version="test",
        force_model_fingerprint=request.force_model.fingerprint(),
        backend_metadata={},
        times_s=times,
        mean_orbits={reference.satellite_id: ref_history, deputy.satellite_id: dep_history},
        cartesian_states={
            reference.satellite_id: tuple(_cartesian(i, 0.0) for i in range(len(times))),
            deputy.satellite_id: tuple(_cartesian(i, 5000.0) for i in range(len(times))),
        },
    )


def _authorized_attempt(request: PropagationRequest, decision) -> PolicyManeuverAttemptEvidence:
    reference = next(sat for sat in request.satellites if sat.role == "reference")
    deputy = next(sat for sat in request.satellites if sat.role == "additional")
    used = 1.0
    remaining = deputy.spacecraft.propellant_mass_kg - used
    dv = 0.03
    maneuver = Maneuver(
        satellite_id=deputy.satellite_id,
        time_s=0.0,
        dv_rtn_m_s=(0.0, dv, 0.0),
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
        propellant_used_kg=used,
        propellant_remaining_kg=remaining,
        required_reserve_kg=5.0,
        replay_backend="orekit-numerical-validation",
        replay_backend_metadata={"gravity_model": "EIGEN-6S"},
        a_matrices=(),
        b_matrices=(),
        disturbances=(),
        mpc_states=(),
        mpc_impulses=(),
        mpc_objective=1.0,
    )
    states = tuple(
        TransitionSpacecraftState(
            satellite_id=sat.satellite_id,
            mean_orbit=sat.mean_orbit,
            cartesian_state=_cartesian(1, 0.0 if sat.role == "reference" else 5000.0),
        )
        for sat in request.satellites
    )
    transition = AuthoritativeTransitionSnapshot(
        continuation_sample_index=1,
        continuation_time_s=60.0,
        source_replay_times_s=(0.0, 60.0),
        controlled_satellite_id=deputy.satellite_id,
        reference_id=reference.satellite_id,
        spacecraft_states=states,
        controlled_propellant_remaining_kg=remaining,
        controlled_total_mass_kg=deputy.spacecraft.dry_mass_kg + remaining,
        event_delta_v_m_s=dv,
        event_propellant_used_kg=used,
        force_model_fingerprint=request.force_model.fingerprint(),
        backend="orekit-numerical-validation",
        backend_version="13.1.7",
        backend_metadata={"gravity_model": "EIGEN-6S"},
        frame=request.frame,
        time_scale=request.time_scale,
        integrator=request.integrator,
    )
    return PolicyManeuverAttemptEvidence(
        decision=decision,
        sizing_attempted=True,
        target=None,
        authority=authority,
        transition=transition,
    )


class CoastSequencePropagator:
    def __init__(self, sequences: tuple[tuple[float, ...], ...]) -> None:
        self._sequences = sequences
        self.calls = 0

    def propagate(self, request: PropagationRequest) -> PropagationResult:
        if self.calls >= len(self._sequences):
            raise AssertionError("unexpected extra coast propagation")
        phases = self._sequences[self.calls]
        self.calls += 1
        return _coast_result(request, phases)


def _patch_authority(monkeypatch) -> None:
    def fake_authorize(
        propagator,
        request,
        constraints,
        decision,
        base_policy,
        times_s,
        windows,
        *,
        deputy_id=None,
    ):
        del propagator, constraints, base_policy, times_s, windows, deputy_id
        return _authorized_attempt(request, decision)

    monkeypatch.setattr(
        "constellation_control.control.campaign.authorize_policy_correction",
        fake_authorize,
    )
    monkeypatch.setattr(
        "constellation_control.control.resume.authorize_policy_correction",
        fake_authorize,
    )


def test_pending_boundary_checkpoint_resume_matches_uninterrupted_campaign(monkeypatch) -> None:
    _patch_authority(monkeypatch)
    seed_request, constraints = _request_at_delta_u(0.0)
    half_width = constraints.phase_corridor_rad
    request, constraints = _request_at_delta_u(half_width)
    sequences = (
        (half_width, 0.0, -half_width),
        (-half_width, 0.0, half_width),
        (half_width, 0.0, -half_width),
    )

    uninterrupted_prop = CoastSequencePropagator(sequences)
    uninterrupted = run_closed_loop_campaign(
        uninterrupted_prop,
        request,
        constraints,
        CorrectionPolicy.BOUNDARY_TO_BOUNDARY,
        _execution_policy(),
        np.asarray([0.0, 60.0]),
        np.asarray([True]),
        campaign_horizon_s=2000.0,
        coast_horizon_s=120.0,
        coast_output_step_s=60.0,
        max_corrections=3,
    )

    first_prop = CoastSequencePropagator(sequences[:1])
    first = run_closed_loop_campaign(
        first_prop,
        request,
        constraints,
        CorrectionPolicy.BOUNDARY_TO_BOUNDARY,
        _execution_policy(),
        np.asarray([0.0, 60.0]),
        np.asarray([True]),
        campaign_horizon_s=2000.0,
        coast_horizon_s=120.0,
        coast_output_step_s=60.0,
        max_corrections=1,
    )
    assert first.termination_reason == "max-corrections-reached"
    assert first.correction_count == 1
    assert [event.elapsed_time_s for event in first.policy_events] == pytest.approx([0.0, 180.0])

    checkpoint = create_campaign_checkpoint(
        first,
        constraints=constraints,
        base_execution_policy=_execution_policy(),
        campaign_horizon_s=2000.0,
        coast_horizon_s=120.0,
        coast_output_step_s=60.0,
        authority_times_s=np.asarray([0.0, 60.0]),
        maneuver_windows=np.asarray([True]),
        max_corrections=3,
        checkpoint_sequence=1,
    )
    assert checkpoint.pending_decision is not None
    assert checkpoint.pending_decision.crossed_boundary_sign == -1

    resumed_prop = CoastSequencePropagator(sequences[1:])
    resumed = resume_closed_loop_campaign(resumed_prop, checkpoint)

    assert resumed.termination_reason == uninterrupted.termination_reason == "max-corrections-reached"
    assert resumed.elapsed_time_s == pytest.approx(uninterrupted.elapsed_time_s)
    assert resumed.final_request == uninterrupted.final_request
    assert resumed.final_policy_armed == uninterrupted.final_policy_armed
    assert resumed.correction_count == uninterrupted.correction_count == 3
    assert resumed.coast_propagation_calls == uninterrupted.coast_propagation_calls == 3
    assert resumed_prop.calls == 2
    assert uninterrupted_prop.calls == 3
    assert [event.elapsed_time_s for event in resumed.policy_events] == pytest.approx(
        [event.elapsed_time_s for event in uninterrupted.policy_events]
    )
    assert [event.crossed_boundary_sign for event in resumed.policy_events] == [
        event.crossed_boundary_sign for event in uninterrupted.policy_events
    ]
    assert [record.elapsed_time_s for record in resumed.policy_trace] == pytest.approx(
        [record.elapsed_time_s for record in uninterrupted.policy_trace]
    )
    assert [record.event_time_s for record in resumed.resource_ledger] == pytest.approx(
        [record.event_time_s for record in uninterrupted.resource_ledger]
    )
    assert resumed.cumulative_delta_v_m_s == pytest.approx(uninterrupted.cumulative_delta_v_m_s)
    assert resumed.cumulative_propellant_used_kg == pytest.approx(
        uninterrupted.cumulative_propellant_used_kg
    )
    assert resumed.resource_ledger[-1].cumulative_delta_v_m_s == pytest.approx(0.09)
    assert resumed.resource_ledger[-1].cumulative_propellant_used_kg == pytest.approx(3.0)
    del seed_request


def test_resume_rejects_tampered_force_identity_before_any_propagation(monkeypatch) -> None:
    _patch_authority(monkeypatch)
    request, constraints = _request_at_delta_u(0.0)
    campaign = run_closed_loop_campaign(
        CoastSequencePropagator(((0.0, 0.0),)),
        request,
        constraints,
        CorrectionPolicy.RETURN_TO_CENTER,
        _execution_policy(),
        np.asarray([0.0, 60.0]),
        np.asarray([True]),
        campaign_horizon_s=60.0,
        coast_horizon_s=60.0,
        coast_output_step_s=60.0,
        max_corrections=2,
    )
    checkpoint = create_campaign_checkpoint(
        campaign,
        constraints=constraints,
        base_execution_policy=_execution_policy(),
        campaign_horizon_s=120.0,
        coast_horizon_s=60.0,
        coast_output_step_s=60.0,
        authority_times_s=np.asarray([0.0, 60.0]),
        maneuver_windows=np.asarray([True]),
        max_corrections=2,
    ).model_copy(update={"force_model_fingerprint": "tampered"})

    class BombPropagator:
        def propagate(self, request):
            raise AssertionError("invalid checkpoint must fail before propagation")

    with pytest.raises(ValueError, match="force-model fingerprint"):
        resume_closed_loop_campaign(BombPropagator(), checkpoint)
