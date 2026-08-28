from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from constellation_control.application.run import load_scenario
from constellation_control.control.campaign import run_closed_loop_campaign
from constellation_control.control.execution import MPCExecutionPolicy, ManeuverAuthorityEvidence
from constellation_control.control.policies import CorrectionPolicy
from constellation_control.control.policy_execution import PolicyManeuverAttemptEvidence
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


def _coast_result(request: PropagationRequest, phase_values: tuple[float, ...]) -> PropagationResult:
    reference = next(sat for sat in request.satellites if sat.role == "reference")
    deputy = next(sat for sat in request.satellites if sat.role == "additional")
    ref_history = tuple(reference.mean_orbit for _ in phase_values)
    dep_history = tuple(
        mean_from_damico_roe(
            reference.mean_orbit,
            RelativeOrbitalElements(0.0, phase, 0.0, 0.0, 0.0, 0.0),
        )
        for phase in phase_values
    )
    times = tuple(float(index * 60) for index in range(len(phase_values)))
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


def _authorized_attempt(request: PropagationRequest, decision, index: int) -> PolicyManeuverAttemptEvidence:
    reference = next(sat for sat in request.satellites if sat.role == "reference")
    deputy = next(sat for sat in request.satellites if sat.role == "additional")
    used = 1.0
    remaining = deputy.spacecraft.propellant_mass_kg - used
    dv = 0.02 + 0.01 * index
    maneuver = Maneuver(satellite_id=deputy.satellite_id, time_s=0.0, dv_rtn_m_s=(0.0, dv, 0.0))
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


def test_boundary_to_boundary_campaign_accumulates_two_authorized_cycles(monkeypatch) -> None:
    request, constraints = _request_at_delta_u(0.1)
    half_width = constraints.phase_corridor_rad
    request, constraints = _request_at_delta_u(half_width)
    authority_calls: list[PropagationRequest] = []

    def fake_authorize(propagator, request, constraints, decision, base_policy, times_s, windows, *, deputy_id=None):
        del propagator, constraints, base_policy, times_s, windows, deputy_id
        authority_calls.append(request)
        return _authorized_attempt(request, decision, len(authority_calls))

    monkeypatch.setattr(
        "constellation_control.control.campaign.authorize_policy_correction",
        fake_authorize,
    )

    class CoastPropagator:
        def __init__(self) -> None:
            self.calls = 0

        def propagate(self, coast_request: PropagationRequest) -> PropagationResult:
            self.calls += 1
            if self.calls == 1:
                return _coast_result(coast_request, (half_width, 0.0, -half_width))
            if self.calls == 2:
                return _coast_result(coast_request, (-half_width, 0.0, half_width))
            raise AssertionError("campaign must stop before a third coast propagation")

    propagator = CoastPropagator()
    result = run_closed_loop_campaign(
        propagator,
        request,
        constraints,
        CorrectionPolicy.BOUNDARY_TO_BOUNDARY,
        _execution_policy(),
        np.asarray([0.0, 60.0]),
        np.asarray([True]),
        campaign_horizon_s=1000.0,
        coast_horizon_s=120.0,
        coast_output_step_s=60.0,
        max_corrections=2,
    )

    assert result.termination_reason == "max-corrections-reached"
    assert result.correction_count == 2
    assert len(result.authority_attempts) == 2
    assert len(result.transitions) == 2
    assert len(result.resource_ledger) == 2
    assert result.coast_propagation_calls == 2
    assert propagator.calls == 2
    assert len(authority_calls) == 2
    assert [event.crossed_boundary_sign for event in result.policy_events] == [1, -1, 1]
    assert result.resource_ledger[0].cumulative_delta_v_m_s == pytest.approx(0.03)
    assert result.resource_ledger[1].cumulative_delta_v_m_s == pytest.approx(0.07)
    assert result.cumulative_propellant_used_kg == pytest.approx(2.0)
    assert result.controlled_propellant_remaining_kg == pytest.approx(
        next(sat for sat in request.satellites if sat.role == "additional").spacecraft.propellant_mass_kg - 2.0
    )
    assert result.model_dump(mode="json")["termination_reason"] == "max-corrections-reached"


def test_no_control_performs_no_propagation_or_authority(monkeypatch) -> None:
    request, constraints = _request_at_delta_u(constraints_half := 0.1)
    del constraints_half

    def bomb_authorize(*args, **kwargs):
        raise AssertionError("NO_CONTROL must not call maneuver authority")

    monkeypatch.setattr(
        "constellation_control.control.campaign.authorize_policy_correction",
        bomb_authorize,
    )

    class BombPropagator:
        def propagate(self, request):
            raise AssertionError("NO_CONTROL must not coast propagate")

    result = run_closed_loop_campaign(
        BombPropagator(),
        request,
        constraints,
        CorrectionPolicy.NO_CONTROL,
        _execution_policy(),
        np.asarray([0.0, 60.0]),
        np.asarray([True]),
        campaign_horizon_s=600.0,
        coast_horizon_s=120.0,
        coast_output_step_s=60.0,
        max_corrections=2,
    )
    assert result.termination_reason == "no-control-policy"
    assert result.correction_count == 0
    assert result.coast_propagation_calls == 0
    assert not result.authority_attempts


def test_rejected_authority_stops_without_fake_transition_or_ledger(monkeypatch) -> None:
    request, constraints = _request_at_delta_u(0.1)
    request, constraints = _request_at_delta_u(constraints.phase_corridor_rad)

    def reject_authorize(propagator, request, constraints, decision, base_policy, times_s, windows, *, deputy_id=None):
        del propagator, constraints, base_policy, times_s, windows, deputy_id
        deputy = next(sat for sat in request.satellites if sat.role == "additional")
        reference = next(sat for sat in request.satellites if sat.role == "reference")
        authority = ManeuverAuthorityEvidence(
            authorized=False,
            reason="propellant-reserve-violation",
            deputy_id=deputy.satellite_id,
            reference_id=reference.satellite_id,
            first_maneuver=None,
            predicted_next_roe=None,
            replay_next_roe=None,
            trust_error_ratio=None,
            replay_min_pair_distance_m=None,
            propellant_used_kg=0.0,
            propellant_remaining_kg=deputy.spacecraft.propellant_mass_kg,
            required_reserve_kg=deputy.spacecraft.propellant_mass_kg,
            replay_backend=None,
            replay_backend_metadata={},
            a_matrices=(),
            b_matrices=(),
            disturbances=(),
            mpc_states=(),
            mpc_impulses=(),
            mpc_objective=0.0,
        )
        return PolicyManeuverAttemptEvidence(decision, True, None, authority, None)

    monkeypatch.setattr(
        "constellation_control.control.campaign.authorize_policy_correction",
        reject_authorize,
    )
    result = run_closed_loop_campaign(
        object(),
        request,
        constraints,
        CorrectionPolicy.RETURN_TO_CENTER,
        _execution_policy(),
        np.asarray([0.0, 60.0]),
        np.asarray([True]),
        campaign_horizon_s=600.0,
        coast_horizon_s=120.0,
        coast_output_step_s=60.0,
        max_corrections=2,
    )
    assert result.termination_reason == "propellant-reserve-reached"
    assert result.correction_count == 0
    assert len(result.authority_attempts) == 1
    assert not result.transitions
    assert not result.resource_ledger


def test_campaign_horizon_stops_no_event_coast_without_hidden_repeat(monkeypatch) -> None:
    request, constraints = _request_at_delta_u(0.0)

    class OneCoastPropagator:
        def __init__(self) -> None:
            self.calls = 0

        def propagate(self, coast_request: PropagationRequest) -> PropagationResult:
            self.calls += 1
            return _coast_result(coast_request, (0.0, 0.0))

    propagator = OneCoastPropagator()
    result = run_closed_loop_campaign(
        propagator,
        request,
        constraints,
        CorrectionPolicy.RETURN_TO_CENTER,
        _execution_policy(),
        np.asarray([0.0, 60.0]),
        np.asarray([True]),
        campaign_horizon_s=60.0,
        coast_horizon_s=600.0,
        coast_output_step_s=60.0,
        max_corrections=2,
    )
    assert result.termination_reason == "campaign-horizon-reached"
    assert result.elapsed_time_s == pytest.approx(60.0)
    assert propagator.calls == 1
