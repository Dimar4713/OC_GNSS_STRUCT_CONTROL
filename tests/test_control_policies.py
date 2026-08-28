from __future__ import annotations

from math import inf, nan

import pytest

from constellation_control.control.policies import (
    CorrectionPolicy,
    CorrectionPolicyState,
    evaluate_correction_policy,
)


@pytest.mark.parametrize("observed", (-0.5, 0.0, 0.5))
def test_no_control_never_requests_inside_corridor(observed: float) -> None:
    decision, state = evaluate_correction_policy(CorrectionPolicy.NO_CONTROL, observed, 1.0)
    assert decision.correction_requested is False
    assert decision.guidance_target_delta_u_rad is None
    assert decision.reason == "no_control_policy"
    assert state == CorrectionPolicyState(armed=True)


@pytest.mark.parametrize("observed", (-2.0, -1.0, 1.0, 2.0))
def test_no_control_never_requests_at_or_outside_boundary(observed: float) -> None:
    decision, _ = evaluate_correction_policy(CorrectionPolicy.NO_CONTROL, observed, 1.0)
    assert decision.correction_requested is False
    assert decision.guidance_target_delta_u_rad is None
    assert decision.crossed_boundary_sign == (1 if observed > 0.0 else -1)


@pytest.mark.parametrize("observed", (-2.0, -1.0, 1.0, 2.0))
def test_return_to_center_requests_exact_zero_at_boundary(observed: float) -> None:
    decision, state = evaluate_correction_policy(CorrectionPolicy.RETURN_TO_CENTER, observed, 1.0)
    assert decision.correction_requested is True
    assert decision.guidance_target_delta_u_rad == 0.0
    assert decision.crossed_boundary_sign == (1 if observed > 0.0 else -1)
    assert decision.reason == "phase_boundary_reached_return_to_center"
    assert state == CorrectionPolicyState(armed=False)


@pytest.mark.parametrize(
    ("observed", "expected_target"),
    [(-2.0, 1.0), (-1.0, 1.0), (1.0, -1.0), (2.0, -1.0)],
)
def test_boundary_to_boundary_targets_opposite_configured_boundary(
    observed: float,
    expected_target: float,
) -> None:
    decision, state = evaluate_correction_policy(CorrectionPolicy.BOUNDARY_TO_BOUNDARY, observed, 1.0)
    assert decision.correction_requested is True
    assert decision.guidance_target_delta_u_rad == expected_target
    assert abs(decision.guidance_target_delta_u_rad) == decision.corridor_half_width_rad
    assert decision.reason == "phase_boundary_reached_coast_to_opposite_boundary"
    assert state == CorrectionPolicyState(armed=False)


@pytest.mark.parametrize(
    "policy",
    (CorrectionPolicy.RETURN_TO_CENTER, CorrectionPolicy.BOUNDARY_TO_BOUNDARY),
)
def test_control_policies_do_not_request_inside_corridor(policy: CorrectionPolicy) -> None:
    decision, state = evaluate_correction_policy(policy, 0.999, 1.0)
    assert decision.correction_requested is False
    assert decision.guidance_target_delta_u_rad is None
    assert decision.crossed_boundary_sign is None
    assert decision.reason == "inside_corridor"
    assert state == CorrectionPolicyState(armed=True)


@pytest.mark.parametrize(
    "policy",
    (CorrectionPolicy.RETURN_TO_CENTER, CorrectionPolicy.BOUNDARY_TO_BOUNDARY),
)
def test_request_disarms_and_repeated_boundary_sample_does_not_duplicate(policy: CorrectionPolicy) -> None:
    first, state = evaluate_correction_policy(policy, 1.0, 1.0)
    assert first.correction_requested is True
    assert state.armed is False

    repeated, repeated_state = evaluate_correction_policy(policy, 1.1, 1.0, state)
    assert repeated.correction_requested is False
    assert repeated.reason == "disarmed_waiting_for_reentry"
    assert repeated.guidance_target_delta_u_rad is None
    assert repeated_state == state


@pytest.mark.parametrize(
    "policy",
    (CorrectionPolicy.RETURN_TO_CENTER, CorrectionPolicy.BOUNDARY_TO_BOUNDARY),
)
def test_policy_rearms_only_strictly_inside_then_can_request_again(policy: CorrectionPolicy) -> None:
    _, state = evaluate_correction_policy(policy, -1.0, 1.0)
    assert state.armed is False

    at_boundary, state_at_boundary = evaluate_correction_policy(policy, -1.0, 1.0, state)
    assert at_boundary.correction_requested is False
    assert state_at_boundary.armed is False

    rearm, armed = evaluate_correction_policy(policy, -0.999, 1.0, state_at_boundary)
    assert rearm.correction_requested is False
    assert rearm.reason == "rearmed_inside_corridor"
    assert armed.armed is True

    second, disarmed_again = evaluate_correction_policy(policy, 1.0, 1.0, armed)
    assert second.correction_requested is True
    assert disarmed_again.armed is False


def test_policy_decision_contract_contains_no_delta_v_or_fuel_fields() -> None:
    decision, _ = evaluate_correction_policy(CorrectionPolicy.RETURN_TO_CENTER, 1.0, 1.0)
    fields = decision.__dataclass_fields__
    assert not any("dv" in name.lower() or "fuel" in name.lower() or "propellant" in name.lower() for name in fields)


@pytest.mark.parametrize(
    ("delta_u", "half_width", "message"),
    [
        (inf, 1.0, "delta_u_rad must be finite"),
        (nan, 1.0, "delta_u_rad must be finite"),
        (0.0, 0.0, "corridor_half_width_rad must be finite and positive"),
        (0.0, -1.0, "corridor_half_width_rad must be finite and positive"),
        (0.0, inf, "corridor_half_width_rad must be finite and positive"),
        (0.0, nan, "corridor_half_width_rad must be finite and positive"),
    ],
)
def test_policy_inputs_are_explicitly_validated(delta_u: float, half_width: float, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        evaluate_correction_policy(CorrectionPolicy.RETURN_TO_CENTER, delta_u, half_width)
