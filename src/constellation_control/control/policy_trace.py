from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

import numpy as np

from constellation_control.analysis.relative_operations import mean_phase_rad
from constellation_control.control.closed_loop import CoastPolicyEvent, CoastScanResult, scan_coast_for_policy_event
from constellation_control.control.policies import (
    CorrectionDecision,
    CorrectionPolicy,
    CorrectionPolicyState,
    evaluate_correction_policy,
)
from constellation_control.domain.models import PropagationResult
from constellation_control.dynamics.orbits import wrap_pi


@dataclass(frozen=True)
class PolicyTraceRecord:
    sample_index: int
    time_s: float
    delta_u_rad: float
    decision_reason: str
    correction_requested: bool
    crossed_boundary_sign: int | None
    guidance_target_delta_u_rad: float | None
    armed_before: bool
    armed_after: bool
    grid_resolution_s: float
    timing_semantics: str


@dataclass(frozen=True)
class TracedCoastScanResult:
    scan: CoastScanResult
    trace: tuple[PolicyTraceRecord, ...]


def _trace_record(
    index: int,
    time_s: float,
    delta_u_rad: float,
    decision: CorrectionDecision,
    output_step_s: float,
) -> PolicyTraceRecord:
    return PolicyTraceRecord(
        sample_index=index,
        time_s=float(time_s),
        delta_u_rad=float(delta_u_rad),
        decision_reason=decision.reason,
        correction_requested=decision.correction_requested,
        crossed_boundary_sign=decision.crossed_boundary_sign,
        guidance_target_delta_u_rad=decision.guidance_target_delta_u_rad,
        armed_before=decision.armed_before,
        armed_after=decision.armed_after,
        grid_resolution_s=float(output_step_s),
        timing_semantics="authoritative propagation output grid; no interpolation",
    )


def scan_coast_for_policy_event_with_trace(
    result: PropagationResult,
    *,
    reference_id: str,
    deputy_id: str,
    policy: CorrectionPolicy,
    corridor_half_width_rad: float,
    initial_state: CorrectionPolicyState,
    output_step_s: float,
) -> TracedCoastScanResult:
    """Retain policy-significant decisions while preserving the accepted coast-event result."""

    step = float(output_step_s)
    if not isfinite(step) or step <= 0.0:
        raise ValueError("output_step_s must be finite and positive")

    accepted = scan_coast_for_policy_event(
        result,
        reference_id=reference_id,
        deputy_id=deputy_id,
        policy=policy,
        corridor_half_width_rad=corridor_half_width_rad,
        initial_state=initial_state,
        output_step_s=step,
    )

    times = np.asarray(result.times_s, dtype=float)
    ref_history = result.mean_orbits[reference_id]
    dep_history = result.mean_orbits[deputy_id]
    state = initial_state
    trace: list[PolicyTraceRecord] = []
    previous_reason: str | None = None
    stop_index = accepted.event.sample_index if accepted.event is not None else len(times) - 1

    for index, (time_s, ref_mean, dep_mean) in enumerate(
        zip(times, ref_history, dep_history, strict=True)
    ):
        if index > stop_index:
            break
        delta_u = wrap_pi(mean_phase_rad(dep_mean) - mean_phase_rad(ref_mean))
        decision, state = evaluate_correction_policy(
            policy,
            delta_u,
            corridor_half_width_rad,
            state,
        )
        significant = (
            index == 0
            or index == stop_index
            or decision.reason != previous_reason
            or decision.reason == "rearmed_inside_corridor"
            or decision.correction_requested
        )
        if significant:
            trace.append(_trace_record(index, float(time_s), delta_u, decision, step))
        previous_reason = decision.reason

    if state != accepted.final_policy_state:
        raise RuntimeError("policy trace final state disagrees with accepted coast scan")
    if accepted.event is not None:
        event: CoastPolicyEvent = accepted.event
        last = trace[-1]
        if last.sample_index != event.sample_index or not last.correction_requested:
            raise RuntimeError("policy trace correction event disagrees with accepted coast scan")

    return TracedCoastScanResult(scan=accepted, trace=tuple(trace))
