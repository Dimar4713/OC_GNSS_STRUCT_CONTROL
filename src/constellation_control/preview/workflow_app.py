from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from constellation_control.application.design_pipeline import run_design_application
from constellation_control.application.robustness import run_robustness_application
from constellation_control.domain.models import ForceMode
from constellation_control.preview.app import (
    _classify_yaml,
    _load_preview_scenario,
    _safe_result_file,
    _safe_scenario_path,
)
from constellation_control.preview.http_app import (
    create_preview_app as create_operations_preview_app,
    render_preview_page_for_test as render_operations_page,
)

PREVIEW_VERSION = "0.1.5"

_DESIGN_ARTIFACTS = {
    "pipeline_manifest.json": "application/json",
    "recommendation.json": "application/json",
    "validation.json": "application/json",
    "candidates.csv": "text/csv",
    "candidates.parquet": "application/octet-stream",
    "pareto.csv": "text/csv",
    "pareto.parquet": "application/octet-stream",
    "report.md": "text/markdown",
    "report.html": "text/html",
}
_ROBUSTNESS_ARTIFACTS = {
    "campaign_manifest.json": "application/json",
    "summary.json": "application/json",
    "samples.csv": "text/csv",
    "samples.parquet": "application/octet-stream",
    "outcomes.csv": "text/csv",
    "outcomes.parquet": "application/octet-stream",
    "statistics.csv": "text/csv",
    "violation_probability.csv": "text/csv",
    "report.md": "text/markdown",
    "report.html": "text/html",
}

_WORKFLOW_CARD = r"""
<div class="card" id="workflowCard">
  <h3>Design / Robustness workflows — Проектирование / Робастность</h3>
  <p class="hint">Запускаются существующие authoritative application workflows. UI не выполняет собственный поиск, propagation или Monte Carlo. / Existing authoritative application workflows are invoked directly. The UI performs no independent search, propagation or Monte Carlo.</p>
  <h4>Design pipeline</h4>
  <label>Screening ScenarioConfig</label><select id="designScreening"></select>
  <label>Validation ScenarioConfig</label><select id="designValidation"></select>
  <label>Design pipeline config</label><select id="designConfig"></select>
  <button onclick="runDesignWorkflow()">Запустить Design / Run Design</button>
  <div id="designStatus" class="status">Выберите явные входы / Select explicit inputs.</div>
  <div id="designLinks" class="oplinks"></div>
  <h4>Robustness campaign</h4>
  <label>Validation ScenarioConfig</label><select id="robustnessValidation"></select>
  <label>Robustness campaign config</label><select id="robustnessConfig"></select>
  <button onclick="runRobustnessWorkflow()">Запустить Robustness / Run Robustness</button>
  <div id="robustnessStatus" class="status">Выберите явные входы / Select explicit inputs.</div>
  <div id="robustnessLinks" class="oplinks"></div>
</div>
"""

_WORKFLOW_SCRIPT = r"""
function workflowOptions(items){return items.map(x=>'<option value="'+closedLoopEsc(x)+'">'+closedLoopEsc(x)+'</option>').join('');}
function populateWorkflowInputs(){
  if(!catalog)return;
  const scenarios=catalog.scenarios||[];
  const design=(catalog.other_inputs||[]).filter(x=>x.kind==='design_pipeline_config').map(x=>x.name);
  const robust=(catalog.other_inputs||[]).filter(x=>x.kind==='robustness_campaign_config').map(x=>x.name);
  document.getElementById('designScreening').innerHTML=workflowOptions(scenarios);
  document.getElementById('designValidation').innerHTML=workflowOptions(scenarios);
  document.getElementById('robustnessValidation').innerHTML=workflowOptions(scenarios);
  document.getElementById('designConfig').innerHTML=workflowOptions(design);
  document.getElementById('robustnessConfig').innerHTML=workflowOptions(robust);
}
function workflowLinks(target, artifacts){document.getElementById(target).innerHTML=Object.entries(artifacts||{}).map(([n,u])=>'<a target="_blank" href="'+closedLoopEsc(u)+'">'+closedLoopEsc(n)+'</a>').join(' ');}
async function runDesignWorkflow(){
  const s=document.getElementById('designStatus');s.textContent='Design выполняется / Design running…';s.className='status';
  const body={screening_scenario_name:designScreening.value,validation_scenario_name:designValidation.value,pipeline_config_name:designConfig.value};
  const r=await fetch('/api/design-runs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const d=await r.json();
  if(!r.ok){s.textContent=d.detail||'Design failed';s.className='status danger';return;}s.textContent='Design завершён / completed: '+d.run_dir;s.className='status ok';workflowLinks('designLinks',d.artifacts);
}
async function runRobustnessWorkflow(){
  const s=document.getElementById('robustnessStatus');s.textContent='Robustness выполняется / running…';s.className='status';
  const body={validation_scenario_name:robustnessValidation.value,campaign_config_name:robustnessConfig.value};
  const r=await fetch('/api/robustness-runs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const d=await r.json();
  if(!r.ok){s.textContent=d.detail||'Robustness failed';s.className='status danger';return;}s.textContent='Robustness завершён / completed: '+d.run_dir;s.className='status ok';workflowLinks('robustnessLinks',d.artifacts);
}
"""


class PreviewDesignRequest(BaseModel):
    screening_scenario_name: str
    validation_scenario_name: str
    pipeline_config_name: str


class PreviewRobustnessRequest(BaseModel):
    validation_scenario_name: str
    campaign_config_name: str


def _workflow_config(scenario_root: Path, name: str, required_kind: str) -> Path:
    path = _safe_scenario_path(scenario_root, name)
    kind, diagnostic = _classify_yaml(path)
    if kind != required_kind:
        raise ValueError(
            f"{name}: неверный тип входа / wrong input kind: expected {required_kind}, got {kind}. "
            f"{diagnostic or ''}"
        )
    return path


def _relative_run(output_root: Path, run_dir: Path) -> tuple[str, str]:
    relative = run_dir.resolve().relative_to(output_root.resolve())
    if len(relative.parts) != 2:
        raise RuntimeError("Неожиданная структура workflow результата / unexpected workflow result layout")
    return relative.parts[0], relative.parts[1]


def _artifact_urls(prefix: str, media_types: dict[str, str]) -> dict[str, str]:
    return {name: f"{prefix}/{name}" for name in media_types}


def render_preview_page_for_test() -> str:
    page = render_operations_page()
    page = page.replace("</section></main>", f"{_WORKFLOW_CARD}</section></main>", 1)
    page = page.replace(
        "bootstrap().catch(e=>setStatus(String(e),'danger'));",
        f"{_WORKFLOW_SCRIPT}\nconst workflowBootstrap=bootstrap;bootstrap=async function(){{await workflowBootstrap();populateWorkflowInputs();}};bootstrap().catch(e=>setStatus(String(e),'danger'));",
        1,
    )
    return page


def _remove_route(app: FastAPI, path: str) -> None:
    app.router.routes[:] = [route for route in app.router.routes if getattr(route, "path", None) != path]


def create_preview_app(scenario_root: Path = Path("scenarios"), output_root: Path = Path("runs")) -> FastAPI:
    app = create_operations_preview_app(scenario_root, output_root)
    app.version = PREVIEW_VERSION
    _remove_route(app, "/")
    _remove_route(app, "/health")

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        return HTMLResponse(render_preview_page_for_test())

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "preview": PREVIEW_VERSION}

    @app.post("/api/design-runs")
    def design_run(request: PreviewDesignRequest) -> dict[str, object]:
        try:
            screening_path, screening = _load_preview_scenario(scenario_root, request.screening_scenario_name)
            validation_path, validation = _load_preview_scenario(scenario_root, request.validation_scenario_name)
            if screening.force_model.mode != ForceMode.SCREENING:
                raise ValueError("Design screening input требует SCREENING force mode / requires SCREENING force mode")
            if validation.force_model.mode != ForceMode.VALIDATION:
                raise ValueError("Design validation input требует VALIDATION force mode / requires VALIDATION force mode")
            pipeline_path = _workflow_config(scenario_root, request.pipeline_config_name, "design_pipeline_config")
            run_dir = run_design_application(screening_path, validation_path, pipeline_path, output_root)
            group, run_id = _relative_run(output_root, run_dir)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        prefix = f"/api/workflow-results/design/{group}/{run_id}"
        return {
            "workflow": "design",
            "run_dir": str(run_dir),
            "authority": "screening search + authoritative orekit-numerical validation",
            "artifacts": _artifact_urls(prefix, _DESIGN_ARTIFACTS),
        }

    @app.post("/api/robustness-runs")
    def robustness_run(request: PreviewRobustnessRequest) -> dict[str, object]:
        try:
            validation_path, validation = _load_preview_scenario(scenario_root, request.validation_scenario_name)
            if validation.force_model.mode != ForceMode.VALIDATION:
                raise ValueError("Robustness input требует VALIDATION force mode / requires VALIDATION force mode")
            campaign_path = _workflow_config(scenario_root, request.campaign_config_name, "robustness_campaign_config")
            run_dir = run_robustness_application(validation_path, campaign_path, output_root)
            group, run_id = _relative_run(output_root, run_dir)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        prefix = f"/api/workflow-results/robustness/{group}/{run_id}"
        return {
            "workflow": "robustness",
            "run_dir": str(run_dir),
            "authority": "orekit-numerical robustness campaign",
            "artifacts": _artifact_urls(prefix, _ROBUSTNESS_ARTIFACTS),
        }

    @app.get("/api/workflow-results/{workflow}/{group}/{run_id}/{name}", response_class=FileResponse)
    def workflow_artifact(workflow: str, group: str, run_id: str, name: str) -> FileResponse:
        media_types = _DESIGN_ARTIFACTS if workflow == "design" else _ROBUSTNESS_ARTIFACTS if workflow == "robustness" else None
        if media_types is None or name not in media_types:
            raise HTTPException(status_code=404, detail="Workflow artifact is not exposed by Preview")
        try:
            path = _safe_result_file(output_root, group, run_id, name)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return FileResponse(path, media_type=media_types[name])

    return app


app = create_preview_app()
