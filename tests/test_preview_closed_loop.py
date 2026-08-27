from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from constellation_control.control.policies import CorrectionPolicy
from constellation_control.domain.models import PropagationRequest, PropagationResult
from constellation_control.preview.closed_loop import (
    PREVIEW_CLOSED_LOOP_PROFILE_SCHEMA,
    PreviewClosedLoopProfile,
    run_preview_closed_loop,
)


def _repo_root() -> Path:
    return Path(__file__).parents[1]


def _profile(policy: CorrectionPolicy = CorrectionPolicy.NO_CONTROL) -> PreviewClosedLoopProfile:
    return PreviewClosedLoopProfile(
        policy=policy,
        campaign_horizon_s=3600.0,
        coast_horizon_s=600.0,
        coast_output_step_s=60.0,
        max_corrections=3,
        authority_times_s=(0.0, 60.0, 120.0),
        maneuver_windows=(True, True),
        max_abs_impulse_rtn_m_s=(0.2, 0.2, 0.2),
        min_impulse_bit_m_s=1.0e-3,
        trust_tolerances_roe=(1.0e-6, 1.0e-3, 1.0e-6, 1.0e-6, 1.0e-6, 1.0e-6),
        target_roe=(0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
        w_tracking=10.0,
        w_max=0.5,
    )


class BombPropagator:
    def __init__(self) -> None:
        self.calls = 0

    def propagate(self, request: PropagationRequest) -> PropagationResult:
        self.calls += 1
        raise AssertionError("NO_CONTROL or preflight rejection must not invoke propagation")


def test_profile_round_trip_and_all_control_values_are_explicit() -> None:
    profile = _profile()
    restored = PreviewClosedLoopProfile.model_validate_json(profile.model_dump_json())
    assert restored == profile
    assert restored.schema_version == PREVIEW_CLOSED_LOOP_PROFILE_SCHEMA

    allowed_defaults = {"schema_version", "deputy_id"}
    defaulted = {
        name
        for name, field in PreviewClosedLoopProfile.model_fields.items()
        if not field.is_required()
    }
    assert defaulted == allowed_defaults


def test_profile_rejects_optimized_policy_and_bad_authority_grid() -> None:
    with pytest.raises(ValidationError, match="OPTIMIZED"):
        _profile().model_copy(update={"policy": CorrectionPolicy.OPTIMIZED}, deep=True)

    payload = _profile().model_dump()
    payload["authority_times_s"] = (0.0, 60.0, 60.0)
    with pytest.raises(ValidationError, match="strictly increasing"):
        PreviewClosedLoopProfile.model_validate(payload)


def test_no_control_runs_without_propagation_and_writes_standard_evidence(tmp_path: Path) -> None:
    propagator = BombPropagator()
    result = run_preview_closed_loop(
        _repo_root() / "scenarios" / "mvp_45deg.yaml",
        tmp_path,
        _profile(CorrectionPolicy.NO_CONTROL),
        propagator=propagator,
    )

    assert propagator.calls == 0
    assert result.campaign.policy == CorrectionPolicy.NO_CONTROL
    assert result.campaign.termination_reason == "no-control-policy"
    assert result.campaign.correction_count == 0
    assert result.campaign.authority_attempts == ()
    run_dir = Path(result.run_dir)
    expected = {
        "closed_loop_profile.json",
        "closed_loop_campaign.json",
        "closed_loop_metrics.json",
        "closed_loop_corrections.csv",
        "closed_loop_corrections.parquet",
        "closed_loop_corrections.json",
        "report.md",
        "report.html",
    }
    assert expected.issubset({path.name for path in run_dir.iterdir()})
    saved_profile = json.loads((run_dir / "closed_loop_profile.json").read_text(encoding="utf-8"))
    assert saved_profile == _profile(CorrectionPolicy.NO_CONTROL).model_dump(mode="json")
    saved_campaign = json.loads((run_dir / "closed_loop_campaign.json").read_text(encoding="utf-8"))
    assert saved_campaign["termination_reason"] == "no-control-policy"


def test_correction_policy_on_screening_scenario_fails_before_propagation(tmp_path: Path) -> None:
    propagator = BombPropagator()
    with pytest.raises(ValueError, match="VALIDATION force mode"):
        run_preview_closed_loop(
            _repo_root() / "scenarios" / "mvp_45deg.yaml",
            tmp_path,
            _profile(CorrectionPolicy.BOUNDARY_TO_BOUNDARY),
            propagator=propagator,
        )
    assert propagator.calls == 0


def test_execution_policy_is_exactly_operator_profile() -> None:
    profile = _profile(CorrectionPolicy.RETURN_TO_CENTER)
    execution = profile.execution_policy()
    assert execution.max_abs_impulse_rtn_m_s == profile.max_abs_impulse_rtn_m_s
    assert execution.min_impulse_bit_m_s == profile.min_impulse_bit_m_s
    assert execution.trust_tolerances_roe == profile.trust_tolerances_roe
    assert execution.target_roe == profile.target_roe
    assert execution.w_tracking == profile.w_tracking
    assert execution.w_max == profile.w_max
