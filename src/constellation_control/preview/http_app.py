from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from constellation_control.preview.app import _safe_result_file, create_preview_app as create_base_preview_app
from constellation_control.preview.closed_loop import PreviewClosedLoopProfile, run_preview_closed_loop

_CLOSED_LOOP_ARTIFACT_MEDIA_TYPES = {
    "closed_loop_profile.json": "application/json",
    "closed_loop_campaign.json": "application/json",
    "closed_loop_metrics.json": "application/json",
    "closed_loop_corrections.json": "application/json",
    "closed_loop_corrections.csv": "text/csv",
    "closed_loop_corrections.parquet": "application/octet-stream",
    "report.md": "text/markdown",
    "report.html": "text/html",
}


class PreviewClosedLoopHttpRequest(BaseModel):
    scenario_name: str
    profile: PreviewClosedLoopProfile


def _load_exact_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def create_preview_app(
    scenario_root: Path = Path("scenarios"),
    output_root: Path = Path("runs"),
) -> FastAPI:
    """Compose accepted Preview P0/P1 routes with the explicit P2 closed-loop API."""

    app = create_base_preview_app(scenario_root, output_root)

    @app.post("/api/closed-loop-runs")
    def closed_loop_run(request: PreviewClosedLoopHttpRequest) -> dict[str, object]:
        try:
            scenario_path = scenario_root.resolve() / request.scenario_name
            # Reuse the base Preview path/classification guard before entering the P2 runner.
            from constellation_control.preview.app import _load_preview_scenario

            safe_path, _ = _load_preview_scenario(scenario_root, request.scenario_name)
            if safe_path.resolve() != scenario_path.resolve():
                raise ValueError("resolved scenario path mismatch")
            execution = run_preview_closed_loop(safe_path, output_root, request.profile)
            run_dir = Path(execution.run_dir)
            relative = run_dir.resolve().relative_to(output_root.resolve())
            if len(relative.parts) != 2:
                raise RuntimeError(
                    "Неожиданная структура каталога closed-loop запуска / "
                    "unexpected closed-loop run directory layout"
                )
            metrics = _load_exact_json(Path(execution.metrics_path))
            corrections = _load_exact_json(Path(execution.corrections_json_path))
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        scenario_id, run_id = relative.parts
        prefix = f"/api/closed-loop-results/{scenario_id}/{run_id}"
        return {
            "run_dir": execution.run_dir,
            "campaign": {
                "policy": execution.campaign.policy.value,
                "termination_reason": execution.campaign.termination_reason,
                "correction_count": execution.campaign.correction_count,
                "authority_attempt_count": len(execution.campaign.authority_attempts),
                "cumulative_delta_v_m_s": execution.campaign.cumulative_delta_v_m_s,
                "cumulative_propellant_used_kg": execution.campaign.cumulative_propellant_used_kg,
                "propellant_remaining_kg": execution.campaign.controlled_propellant_remaining_kg,
                "required_reserve_kg": execution.campaign.controlled_required_reserve_kg,
                "force_model_fingerprint": execution.campaign.final_request.force_model.fingerprint(),
                "frame": execution.campaign.final_request.frame.value,
                "time_scale": execution.campaign.final_request.time_scale.value,
            },
            "metrics": metrics,
            "corrections": corrections,
            "artifacts": {
                name: f"{prefix}/{name}" for name in _CLOSED_LOOP_ARTIFACT_MEDIA_TYPES
            },
        }

    @app.get(
        "/api/closed-loop-results/{scenario_id}/{run_id}/{name}",
        response_class=FileResponse,
    )
    def closed_loop_artifact(scenario_id: str, run_id: str, name: str) -> FileResponse:
        media_type = _CLOSED_LOOP_ARTIFACT_MEDIA_TYPES.get(name)
        if media_type is None:
            raise HTTPException(
                status_code=404,
                detail="Closed-loop result artifact is not exposed by Preview",
            )
        try:
            path = _safe_result_file(output_root, scenario_id, run_id, name)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return FileResponse(path, media_type=media_type)

    return app


app = create_preview_app()
