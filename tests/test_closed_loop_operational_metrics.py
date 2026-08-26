from __future__ import annotations

from pathlib import Path

import pytest

from constellation_control.analysis.closed_loop_metrics import DAY_S, JULIAN_YEAR_S, analyze_closed_loop_operations
from constellation_control.application.run import load_scenario
from constellation_control.control.campaign import ClosedLoopCampaignResult
from constellation_control.control.policies import CorrectionPolicy
from constellation_control.control.transition import CorrectionResourceRecord
from constellation_control.domain.models import PropagationRequest


def _request() -> PropagationRequest:
    scenario = load_scenario(Path(__file__).parents[1] / "scenarios" / "mvp_45deg.yaml")
    return PropagationRequest(
        scenario_id=scenario.scenario_id,
        epoch=scenario.epoch,
        frame=scenario.frame,
        time_scale=scenario.time_scale,
        satellites=scenario.constellation.satellites,
        maneuvers=(),
        duration_s=60.0,
        output_step_s=60.0,
        force_model=scenario.force_model,
        integrator=scenario.integrator,
        seed=scenario.seed,
    )


def _record(
    *,
    event_time_s: float,
    dv: float,
    propellant: float,
    remaining: float,
    reserve: float,
    cumulative_dv: float,
    cumulative_propellant: float,
) -> CorrectionResourceRecord:
    return CorrectionResourceRecord(
        event_time_s=event_time_s,
        policy=CorrectionPolicy.BOUNDARY_TO_BOUNDARY.value,
        policy_reason="phase_boundary_reached_coast_to_opposite_boundary",
        crossed_boundary_sign=1,
        observed_delta_u_rad=0.1,
        guidance_target_delta_u_rad=-0.1,
        dv_rtn_m_s=(0.0, dv, 0.0),
        delta_v_m_s=dv,
        propellant_used_kg=propellant,
        propellant_remaining_kg=remaining,
        required_reserve_kg=reserve,
        cumulative_delta_v_m_s=cumulative_dv,
        cumulative_propellant_used_kg=cumulative_propellant,
        replay_backend="orekit-numerical-validation",
        replay_backend_metadata={"gravity_model": "EIGEN-6S"},
        force_model_fingerprint=_request().force_model.fingerprint(),
    )


def _campaign(
    ledger: tuple[CorrectionResourceRecord, ...],
    *,
    elapsed_s: float,
    remaining: float,
    reserve: float,
) -> ClosedLoopCampaignResult:
    request = _request()
    cumulative_dv = ledger[-1].cumulative_delta_v_m_s if ledger else 0.0
    cumulative_propellant = ledger[-1].cumulative_propellant_used_kg if ledger else 0.0
    return ClosedLoopCampaignResult(
        policy=CorrectionPolicy.BOUNDARY_TO_BOUNDARY,
        corridor_half_width_rad=0.1,
        initial_epoch_iso=request.epoch.isoformat(),
        final_epoch_iso=request.epoch.isoformat(),
        elapsed_time_s=elapsed_s,
        correction_count=len(ledger),
        coast_propagation_calls=0,
        termination_reason="test",
        final_policy_armed=False,
        policy_events=(),
        authority_attempts=(),
        transitions=(),
        resource_ledger=ledger,
        cumulative_delta_v_m_s=cumulative_dv,
        cumulative_propellant_used_kg=cumulative_propellant,
        controlled_propellant_remaining_kg=remaining,
        controlled_required_reserve_kg=reserve,
        final_request=request,
    )


def test_two_correction_history_produces_exact_annualized_rates_and_lifetime() -> None:
    ledger = (
        _record(
            event_time_s=0.0,
            dv=0.1,
            propellant=1.0,
            remaining=42.0,
            reserve=10.0,
            cumulative_dv=0.1,
            cumulative_propellant=1.0,
        ),
        _record(
            event_time_s=4.0 * DAY_S,
            dv=0.2,
            propellant=2.0,
            remaining=40.0,
            reserve=10.0,
            cumulative_dv=0.3,
            cumulative_propellant=3.0,
        ),
    )
    metrics = analyze_closed_loop_operations(
        _campaign(ledger, elapsed_s=10.0 * DAY_S, remaining=40.0, reserve=10.0)
    )

    assert metrics.correction_intervals.days.count == 1
    assert metrics.correction_intervals.days.mean == pytest.approx(4.0)
    assert metrics.delta_v_per_correction_m_s.mean == pytest.approx(0.15)
    assert metrics.propellant_per_correction_kg.mean == pytest.approx(1.5)
    assert metrics.annualized.available
    assert metrics.annualized.delta_v_m_s_per_day == pytest.approx(0.03)
    assert metrics.annualized.delta_v_m_s_per_julian_year == pytest.approx(0.3 / (10.0 * DAY_S) * JULIAN_YEAR_S)
    assert metrics.annualized.propellant_kg_per_day == pytest.approx(0.3)
    assert metrics.annualized.propellant_kg_per_julian_year == pytest.approx(3.0 / (10.0 * DAY_S) * JULIAN_YEAR_S)
    assert metrics.annualized.corrections_per_julian_year == pytest.approx(2.0 / (10.0 * DAY_S) * JULIAN_YEAR_S)
    expected_propellant_per_year = 3.0 / (10.0 * DAY_S) * JULIAN_YEAR_S
    assert metrics.annualized.usable_propellant_above_reserve_kg == pytest.approx(30.0)
    assert metrics.annualized.projected_years_to_reserve == pytest.approx(30.0 / expected_propellant_per_year)
    assert metrics.annualized.projected_remaining_corrections_to_reserve == pytest.approx(20.0)
    assert metrics.annualized.lifetime_projection_available
    assert not metrics.rearm_settling_available
    assert metrics.model_dump(mode="json")["annualized"]["available"] is True


def test_one_correction_history_refuses_annualization() -> None:
    ledger = (
        _record(
            event_time_s=0.0,
            dv=0.1,
            propellant=1.0,
            remaining=40.0,
            reserve=10.0,
            cumulative_dv=0.1,
            cumulative_propellant=1.0,
        ),
    )
    metrics = analyze_closed_loop_operations(
        _campaign(ledger, elapsed_s=10.0 * DAY_S, remaining=40.0, reserve=10.0)
    )
    assert not metrics.annualized.available
    assert metrics.annualized.unavailable_reason == "annualization-requires-at-least-two-authorized-corrections"
    assert metrics.annualized.delta_v_m_s_per_julian_year is None
    assert metrics.annualized.projected_years_to_reserve is None


def test_zero_consumption_history_has_explicit_unavailable_lifetime_semantics() -> None:
    ledger = (
        _record(
            event_time_s=0.0,
            dv=0.0,
            propellant=0.0,
            remaining=40.0,
            reserve=10.0,
            cumulative_dv=0.0,
            cumulative_propellant=0.0,
        ),
        _record(
            event_time_s=DAY_S,
            dv=0.0,
            propellant=0.0,
            remaining=40.0,
            reserve=10.0,
            cumulative_dv=0.0,
            cumulative_propellant=0.0,
        ),
    )
    metrics = analyze_closed_loop_operations(
        _campaign(ledger, elapsed_s=2.0 * DAY_S, remaining=40.0, reserve=10.0)
    )
    assert metrics.annualized.available
    assert metrics.annualized.propellant_kg_per_julian_year == pytest.approx(0.0)
    assert not metrics.annualized.lifetime_projection_available
    assert metrics.annualized.lifetime_projection_reason == "zero-observed-propellant-consumption-rate"
    assert metrics.annualized.projected_years_to_reserve is None


def test_variable_correction_intervals_expose_dispersion() -> None:
    ledger = (
        _record(
            event_time_s=0.0,
            dv=0.1,
            propellant=1.0,
            remaining=42.0,
            reserve=10.0,
            cumulative_dv=0.1,
            cumulative_propellant=1.0,
        ),
        _record(
            event_time_s=DAY_S,
            dv=0.2,
            propellant=1.0,
            remaining=41.0,
            reserve=10.0,
            cumulative_dv=0.3,
            cumulative_propellant=2.0,
        ),
        _record(
            event_time_s=4.0 * DAY_S,
            dv=0.3,
            propellant=1.0,
            remaining=40.0,
            reserve=10.0,
            cumulative_dv=0.6,
            cumulative_propellant=3.0,
        ),
    )
    metrics = analyze_closed_loop_operations(
        _campaign(ledger, elapsed_s=5.0 * DAY_S, remaining=40.0, reserve=10.0)
    )
    days = metrics.correction_intervals.days
    assert days.count == 2
    assert days.minimum == pytest.approx(1.0)
    assert days.median == pytest.approx(2.0)
    assert days.mean == pytest.approx(2.0)
    assert days.maximum == pytest.approx(3.0)
