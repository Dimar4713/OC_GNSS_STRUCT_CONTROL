from __future__ import annotations

import html
import json
from pathlib import Path

import pandas as pd

from constellation_control.analysis.closed_loop_metrics import ClosedLoopOperationalMetrics
from constellation_control.analysis.relative_operations import mean_phase_rad
from constellation_control.control.campaign import (
    CampaignPolicyEventRecord,
    ClosedLoopCampaignResult,
)
from constellation_control.control.checkpoint import ClosedLoopCampaignCheckpoint
from constellation_control.dynamics.orbits import wrap_pi


def _matching_event(
    campaign: ClosedLoopCampaignResult,
    event_time_s: float,
) -> CampaignPolicyEventRecord:
    matches = [
        event
        for event in campaign.policy_events
        if event.guidance_target_delta_u_rad is not None
        and abs(event.elapsed_time_s - event_time_s) <= 1.0e-9
    ]
    if len(matches) != 1:
        raise ValueError(
            "every authorized resource record must link to exactly one correction policy event"
        )
    return matches[0]


def correction_event_table(campaign: ClosedLoopCampaignResult) -> pd.DataFrame:
    """Project accepted correction evidence into one auditable row per authorized correction."""

    authorized = tuple(record for record in campaign.authority_attempts if record.authorized)
    ledger = campaign.resource_ledger
    transitions = campaign.transitions
    if not (len(authorized) == len(ledger) == len(transitions)):
        raise ValueError(
            "authorized authority attempts, transition snapshots and resource ledger must be 1:1"
        )

    rows: list[dict[str, object]] = []
    for index, (authority, resource, transition) in enumerate(
        zip(authorized, ledger, transitions, strict=True),
        start=1,
    ):
        if abs(authority.elapsed_time_s - resource.event_time_s) > 1.0e-9:
            raise ValueError("authority and resource event times do not match")
        event = _matching_event(campaign, resource.event_time_s)
        if event.decision_reason != resource.policy_reason:
            raise ValueError("policy event reason does not match resource ledger")
        if event.crossed_boundary_sign != resource.crossed_boundary_sign:
            raise ValueError("policy event boundary sign does not match resource ledger")
        if event.guidance_target_delta_u_rad is None:
            raise ValueError("authorized correction event is missing guidance target")
        if abs(event.guidance_target_delta_u_rad - resource.guidance_target_delta_u_rad) > 1.0e-12:
            raise ValueError("policy event guidance target does not match resource ledger")
        if transition.event_delta_v_m_s != resource.delta_v_m_s:
            raise ValueError("transition delta-V does not match resource ledger")
        if transition.force_model_fingerprint != resource.force_model_fingerprint:
            raise ValueError("transition force fingerprint does not match resource ledger")

        states = {state.satellite_id: state for state in transition.spacecraft_states}
        try:
            controlled = states[transition.controlled_satellite_id]
            reference = states[transition.reference_id]
        except KeyError as exc:
            raise ValueError("transition snapshot lacks controlled/reference continuation state") from exc
        post_delta_u = wrap_pi(
            mean_phase_rad(controlled.mean_orbit) - mean_phase_rad(reference.mean_orbit)
        )
        rows.append(
            {
                "correction_index": index,
                "event_time_s": resource.event_time_s,
                "policy": resource.policy,
                "policy_reason": resource.policy_reason,
                "crossed_boundary_sign": resource.crossed_boundary_sign,
                "pre_correction_delta_u_rad": event.observed_delta_u_rad,
                "guidance_target_delta_u_rad": resource.guidance_target_delta_u_rad,
                "post_transition_time_offset_s": transition.continuation_time_s,
                "post_transition_delta_u_rad": post_delta_u,
                "post_transition_semantics": (
                    "direct mean-element Delta u from authoritative continuation snapshot "
                    "after the first accepted control interval; not an instantaneous maneuver jump"
                ),
                "dv_rtn_r_m_s": resource.dv_rtn_m_s[0],
                "dv_rtn_t_m_s": resource.dv_rtn_m_s[1],
                "dv_rtn_n_m_s": resource.dv_rtn_m_s[2],
                "delta_v_m_s": resource.delta_v_m_s,
                "propellant_used_kg": resource.propellant_used_kg,
                "propellant_remaining_kg": resource.propellant_remaining_kg,
                "required_reserve_kg": resource.required_reserve_kg,
                "cumulative_delta_v_m_s": resource.cumulative_delta_v_m_s,
                "cumulative_propellant_used_kg": resource.cumulative_propellant_used_kg,
                "authority_reason": authority.reason,
                "authority_replay_backend": authority.replay_backend,
                "transition_backend": transition.backend,
                "transition_backend_version": transition.backend_version,
                "force_model_fingerprint": transition.force_model_fingerprint,
                "controlled_satellite_id": transition.controlled_satellite_id,
                "reference_id": transition.reference_id,
                "post_transition_states_json": json.dumps(
                    [state.model_dump(mode="json") for state in transition.spacecraft_states],
                    sort_keys=True,
                ),
                "transition_backend_metadata_json": json.dumps(
                    transition.backend_metadata,
                    sort_keys=True,
                ),
            }
        )
    return pd.DataFrame(rows)


def _distribution_summary(label: str, distribution: object) -> str:
    data = distribution.model_dump()  # type: ignore[attr-defined]
    return (
        f"- {label}: count `{data['count']}`, min `{data['minimum']}`, "
        f"median `{data['median']}`, mean `{data['mean']}`, max `{data['maximum']}`"
    )


def _closed_loop_report_section(
    campaign: ClosedLoopCampaignResult,
    metrics: ClosedLoopOperationalMetrics,
    corrections: pd.DataFrame,
    checkpoint: ClosedLoopCampaignCheckpoint | None,
) -> str:
    annualized = metrics.annualized
    lines = [
        "## Closed-loop control campaign",
        "",
        f"- Policy: `{campaign.policy.value}`",
        f"- Configured Delta u corridor half-width: `{campaign.corridor_half_width_rad} rad`",
        f"- Termination reason: `{campaign.termination_reason}`",
        f"- Simulated span: `{campaign.elapsed_time_s} s` (`{metrics.observed_elapsed_days} days`)",
        f"- Authorized corrections: `{campaign.correction_count}`",
        f"- Cumulative delta-V: `{campaign.cumulative_delta_v_m_s} m/s`",
        f"- Cumulative propellant used: `{campaign.cumulative_propellant_used_kg} kg`",
        f"- Remaining propellant: `{campaign.controlled_propellant_remaining_kg} kg`",
        f"- Required reserve: `{campaign.controlled_required_reserve_kg} kg`",
        "",
        "### Cycle timing",
        "",
        _distribution_summary("Correction-to-correction interval, s", metrics.correction_intervals.seconds),
        _distribution_summary("Correction-to-rearm settling, s", metrics.rearm_settling_intervals.seconds),
        _distribution_summary("Rearm-to-next-correction coast, s", metrics.post_rearm_coast_intervals.seconds),
        "",
        "### Annualized operations and lifetime projection",
        "",
        f"- Annualization available: `{annualized.available}`; evidence corrections: `{annualized.evidence_correction_count}`; observed span: `{annualized.evidence_span_days} days`",
        f"- Delta-V: `{annualized.delta_v_m_s_per_day} m/s/day`, `{annualized.delta_v_m_s_per_julian_year} m/s/Julian-year`",
        f"- Propellant: `{annualized.propellant_kg_per_day} kg/day`, `{annualized.propellant_kg_per_julian_year} kg/Julian-year`",
        f"- Projected corrections/Julian-year: `{annualized.corrections_per_julian_year}`",
        f"- Lifetime projection available: `{annualized.lifetime_projection_available}`; reason: `{annualized.lifetime_projection_reason}`",
        f"- Projected years to configured reserve: `{annualized.projected_years_to_reserve}`",
        f"- Projected remaining corrections to reserve: `{annualized.projected_remaining_corrections_to_reserve}`",
        "",
        "Annualized and lifetime values are projections from the stated evidence span, not guaranteed lifetime.",
        "",
        "### Authorized corrections",
        "",
        "Pre-correction Delta u is the direct mean-element policy observation. Post-transition Delta u is derived from the authoritative continuation snapshot after the first accepted control interval; it is not an instantaneous maneuver jump.",
        "",
        "| # | t, s | Reason | Delta u before, rad | Target, rad | Delta u after transition, rad | Delta-V, m/s | Fuel used, kg | Fuel remaining, kg |",
        "| ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in corrections.to_dict(orient="records"):
        lines.append(
            f"| {row['correction_index']} | {row['event_time_s']} | {row['policy_reason']} | "
            f"{row['pre_correction_delta_u_rad']} | {row['guidance_target_delta_u_rad']} | "
            f"{row['post_transition_delta_u_rad']} | {row['delta_v_m_s']} | "
            f"{row['propellant_used_kg']} | {row['propellant_remaining_kg']} |"
        )
    lines.extend(
        [
            "",
            "### Checkpoint / resume evidence",
            "",
        ]
    )
    if checkpoint is None:
        lines.append("No checkpoint artifact was supplied for this publication pass.")
    else:
        lines.extend(
            [
                f"- Checkpoint schema: `{checkpoint.schema_version}`",
                f"- Sequence: `{checkpoint.checkpoint_sequence}`",
                f"- Source termination: `{checkpoint.source_termination_reason}`",
                f"- Simulated progress: `{checkpoint.progress.simulated_progress_fraction}`",
                f"- Remaining simulated time: `{checkpoint.progress.remaining_simulated_s} s`",
                f"- Pending boundary decision: `{checkpoint.pending_decision is not None}`",
                f"- Force-model fingerprint: `{checkpoint.force_model_fingerprint}`",
                f"- Frame / time scale: `{checkpoint.frame}` / `{checkpoint.time_scale}`",
                f"- Scenario: `{checkpoint.current_request.scenario_id}`; seed: `{checkpoint.current_request.seed}`",
            ]
        )
    lines.extend(
        [
            "",
            "Machine-readable evidence: `closed_loop_campaign.json`, `closed_loop_metrics.json`, `closed_loop_corrections.*`, and `closed_loop_checkpoint.json` when supplied.",
            "",
        ]
    )
    return "\n".join(lines)


def _inject_report_section(output_dir: Path, section: str) -> None:
    report_path = output_dir / "report.md"
    existing = report_path.read_text(encoding="utf-8") if report_path.exists() else ""
    marker = "## Secondary diagnostics"
    if marker in existing:
        updated = existing.replace(marker, f"{section}\n{marker}", 1)
    elif existing:
        updated = f"{existing.rstrip()}\n\n{section}"
    else:
        updated = section
    report_path.write_text(updated, encoding="utf-8")
    (output_dir / "report.html").write_text(
        f"<html><body><pre>{html.escape(updated)}</pre></body></html>",
        encoding="utf-8",
    )


def write_closed_loop_artifacts(
    output_dir: Path,
    campaign: ClosedLoopCampaignResult,
    metrics: ClosedLoopOperationalMetrics,
    *,
    checkpoint: ClosedLoopCampaignCheckpoint | None = None,
) -> pd.DataFrame:
    """Publish accepted closed-loop evidence without invoking propagation or control."""

    output_dir.mkdir(parents=True, exist_ok=True)
    corrections = correction_event_table(campaign)
    (output_dir / "closed_loop_campaign.json").write_text(
        campaign.model_dump_json(indent=2),
        encoding="utf-8",
    )
    (output_dir / "closed_loop_metrics.json").write_text(
        metrics.model_dump_json(indent=2),
        encoding="utf-8",
    )
    corrections.to_csv(output_dir / "closed_loop_corrections.csv", index=False)
    corrections.to_parquet(output_dir / "closed_loop_corrections.parquet", index=False)
    corrections.to_json(
        output_dir / "closed_loop_corrections.json",
        orient="records",
        indent=2,
    )
    if checkpoint is not None:
        (output_dir / "closed_loop_checkpoint.json").write_text(
            checkpoint.model_dump_json(indent=2),
            encoding="utf-8",
        )
    section = _closed_loop_report_section(campaign, metrics, corrections, checkpoint)
    _inject_report_section(output_dir, section)
    return corrections
