from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from constellation_control.preview.app import _safe_result_file
from constellation_control.preview.optimal_operations_decision import PreviewOperationalDecisionPolicy
from constellation_control.preview.optimal_operations_profile import PreviewOptimalOperationsStudyProfile
from constellation_control.preview.optimal_operations_release import (
    PROFILE_FILE,
    RELEASE_INPUTS_FILE,
    run_preview_optimal_operations_decision_release,
    run_preview_optimal_operations_foundation_release,
)
from constellation_control.preview.workflow_app import (
    _relative_run,
    _workflow_config,
    create_preview_app as create_workflow_preview_app,
    render_preview_page_for_test as render_workflow_page,
)

PREVIEW_VERSION = "0.2.0"

_OPTIMAL_FOUNDATION_ARTIFACTS = {
    PROFILE_FILE: "application/json",
    RELEASE_INPUTS_FILE: "application/json",
    "optimal_operations_preflight.json": "application/json",
    "operational_baselines.json": "application/json",
    "screening_candidates.json": "application/json",
    "foundation_manifest.json": "application/json",
}
_OPTIMAL_AUTHORITY_ARTIFACTS = {
    "optimized_candidate_selection.json": "application/json",
    "hybrid_authority.json": "application/json",
    "optimized_evaluation.json": "application/json",
    "authority_manifest.json": "application/json",
}
_OPTIMAL_DECISION_ARTIFACTS = {
    "operational_study.json": "application/json",
    "paired_robustness.json": "application/json",
    "operational_decision.json": "application/json",
    "decision_manifest.json": "application/json",
}
_OPTIMAL_ARTIFACTS = {
    **_OPTIMAL_FOUNDATION_ARTIFACTS,
    **_OPTIMAL_AUTHORITY_ARTIFACTS,
    **_OPTIMAL_DECISION_ARTIFACTS,
}

_OPTIMAL_CARD = r"""
<div class="card" id="optimalOperationsCard">
  <h3>Optimal Operations Workspace 0.2 / Рабочее место оптимальных операций</h3>
  <p class="hint"><b>Authority:</b> DSST DESIGN = screening only; Orekit numerical VALIDATION = authority. Screening candidate never becomes operationally credible by UI action. / DSST DESIGN = только screening; authority только Orekit numerical VALIDATION.</p>
  <h4>1. Foundation + screening / Базовые стратегии + поиск</h4>
  <label>DSST DESIGN ScenarioConfig</label><select id="optimalDesignScenario"></select>
  <label>Numerical VALIDATION ScenarioConfig</label><select id="optimalValidationScenario"></select>
  <label for="optimalProfile"><b>Explicit study profile JSON / Явный профиль исследования JSON</b></label>
  <textarea id="optimalProfile" rows="18" style="width:100%;box-sizing:border-box" placeholder="No control/search/robustness numbers are prefilled. Paste the complete PreviewOptimalOperationsStudyProfile JSON."></textarea>
  <button onclick="runOptimalFoundation()">Run foundation + screening / Запустить базу + screening</button>
  <div id="optimalFoundationStatus" class="status">Explicit inputs required / Требуются явные входы.</div>
  <div id="optimalPreflight"></div>
  <label>Selected screening candidate / Выбранный screening candidate</label><select id="optimalCandidate"><option value="">— explicit selection / явный выбор —</option></select>
  <div id="optimalFoundationLinks" class="oplinks"></div>

  <h4>2. Numerical authority + paired robustness + decision</h4>
  <label>Robustness campaign config</label><select id="optimalRobustnessConfig"></select>
  <label for="optimalHybridStep">Hybrid validation output step, s / Шаг hybrid validation, с</label>
  <input id="optimalHybridStep" type="number" min="0" step="any" placeholder="required / обязательно">
  <label for="optimalBracketPadding">Screening bracket padding steps / Расширение bracket, шагов</label>
  <input id="optimalBracketPadding" type="number" min="0" step="1" placeholder="required / обязательно">
  <label for="optimalDecisionPolicy"><b>Explicit decision policy JSON / Явная политика решения JSON</b></label>
  <textarea id="optimalDecisionPolicy" rows="10" style="width:100%;box-sizing:border-box" placeholder="Required: recommendation_strategy_id, robustness_required, violation_probability_limits, violation_probability_objectives. No risk thresholds are prefilled."></textarea>
  <button onclick="runOptimalDecision()">Run authority + robustness + decision / Запустить authority + robustness + решение</button>
  <div id="optimalDecisionStatus" class="status">Foundation run required / Сначала выполните foundation.</div>
  <div id="optimalStrategyTable"></div>
  <div id="optimalRecommendation"></div>
  <div id="optimalDecisionLinks" class="oplinks"></div>
</div>
"""

_OPTIMAL_SCRIPT = r"""
let optimalFoundationGroup=null,optimalFoundationRunId=null;
function optEsc(v){return String(v).replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[c]));}
function optFmt(v){return v===null||v===undefined?'—':String(v);}
function optOptions(items){return items.map(x=>'<option value="'+optEsc(x)+'">'+optEsc(x)+'</option>').join('');}
function populateOptimalInputs(){
  if(!catalog)return;
  const scenarios=catalog.scenarios||[];
  const robust=(catalog.other_inputs||[]).filter(x=>x.kind==='robustness_campaign_config').map(x=>x.name);
  optimalDesignScenario.innerHTML=optOptions(scenarios);
  optimalValidationScenario.innerHTML=optOptions(scenarios);
  optimalRobustnessConfig.innerHTML=optOptions(robust);
}
function optLinks(target,artifacts){document.getElementById(target).innerHTML=Object.entries(artifacts||{}).map(([n,u])=>'<a target="_blank" href="'+optEsc(u)+'">'+optEsc(n)+'</a>').join(' ');}
function renderOptimalPreflight(d){
  const p=d.preflight||{},i=p.identity||{};
  optimalPreflight.innerHTML='<h4>Preflight identity / Идентичность</h4><div class="table-wrap"><table>'+
    '<tr><th>Field</th><th>Evidence</th></tr>'+
    '<tr><td>study</td><td>'+optEsc(p.study_id)+'</td></tr>'+
    '<tr><td>scenario hash</td><td><code>'+optEsc(p.scenario_config_hash)+'</code></td></tr>'+
    '<tr><td>force fingerprint</td><td><code>'+optEsc(i.force_model_fingerprint)+'</code></td></tr>'+
    '<tr><td>frame / time</td><td>'+optEsc(i.frame)+' / '+optEsc(i.time_scale)+'</td></tr>'+
    '<tr><td>controlled / reference</td><td>'+optEsc(p.controlled_deputy_id)+' / '+optEsc(p.reference_id)+'</td></tr>'+
    '<tr><td>execution policy identity</td><td><code>'+optEsc(i.execution_policy_identity)+'</code></td></tr>'+
    '<tr><td>uncertainty identity</td><td><code>'+optEsc(i.uncertainty_model_id)+'</code></td></tr>'+
    '</table></div>';
}
async function runOptimalFoundation(){
  const s=optimalFoundationStatus,raw=optimalProfile.value.trim();
  if(!raw){s.textContent='Study profile JSON required / Требуется JSON-профиль.';s.className='status danger';return;}
  let profile;try{profile=JSON.parse(raw);}catch(e){s.textContent='Invalid profile JSON: '+String(e);s.className='status danger';return;}
  s.textContent='Running authoritative baselines + DSST screening… / Выполняется…';s.className='status';
  const body={design_scenario_name:optimalDesignScenario.value,validation_scenario_name:optimalValidationScenario.value,profile};
  const r=await fetch('/api/optimal-operations/foundation-runs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const d=await r.json();
  if(!r.ok){s.textContent=d.detail||'Foundation failed';s.className='status danger';return;}
  optimalFoundationGroup=d.foundation_group;optimalFoundationRunId=d.foundation_run_id;
  s.textContent='Foundation completed / База завершена: '+d.foundation_run_id;s.className='status ok';renderOptimalPreflight(d);
  optimalCandidate.innerHTML='<option value="">— explicit selection / явный выбор —</option>'+d.candidates.map(x=>'<option value="'+optEsc(x.candidate_id)+'">'+optEsc(x.candidate_id)+' | trigger='+optEsc(x.trigger_fraction)+' target='+optEsc(x.target_fraction)+' | feasible='+optEsc(x.feasible)+'</option>').join('');
  optLinks('optimalFoundationLinks',d.artifacts);
}
function renderOptimalStudy(d){
  const ev=(d.study&&d.study.evaluations)||[],pareto=new Set(d.credible_pareto_strategy_ids||[]);
  let h='<h4>Authoritative strategy evidence / Авторитетные данные стратегий</h4><div class="table-wrap"><table><tr><th>Strategy</th><th>Credibility</th><th>Hard pass</th><th>ΔV m/s</th><th>Fuel kg</th><th>Corridor margin rad</th><th>Fleet margin m</th><th>Robustness</th><th>Pareto</th></tr>';
  for(const x of ev){const hard=(x.hard_constraints||[]).every(y=>y.margin>=0);h+='<tr><td>'+optEsc(x.strategy_id)+'</td><td>'+optEsc(x.credibility_state)+'</td><td>'+optEsc(hard)+'</td><td>'+optEsc(optFmt(x.cumulative_delta_v_m_s))+'</td><td>'+optEsc(optFmt(x.cumulative_propellant_used_kg))+'</td><td>'+optEsc(optFmt(x.minimum_corridor_margin_rad))+'</td><td>'+optEsc(optFmt(x.minimum_fleet_distance_margin_m))+'</td><td>'+optEsc(x.robustness_available)+'</td><td>'+optEsc(pareto.has(x.strategy_id))+'</td></tr>';}
  h+='</table></div>';optimalStrategyTable.innerHTML=h;
  optimalRecommendation.innerHTML='<h4>Recommendation / Рекомендация</h4><div class="status ok"><b>'+optEsc(optFmt(d.recommendation_strategy_id))+'</b><br>decision evidence: <code>'+optEsc(d.decision_evidence_sha256)+'</code></div>';
}
async function runOptimalDecision(){
  const s=optimalDecisionStatus;
  if(!optimalFoundationGroup||!optimalFoundationRunId){s.textContent='Run foundation first / Сначала foundation.';s.className='status danger';return;}
  if(!optimalCandidate.value){s.textContent='Select candidate explicitly / Явно выберите candidate.';s.className='status danger';return;}
  const raw=optimalDecisionPolicy.value.trim();if(!raw){s.textContent='Decision policy JSON required / Требуется policy JSON.';s.className='status danger';return;}
  let policy;try{policy=JSON.parse(raw);}catch(e){s.textContent='Invalid decision policy JSON: '+String(e);s.className='status danger';return;}
  if(optimalHybridStep.value===''||optimalBracketPadding.value===''){s.textContent='Hybrid step and bracket padding are explicit required inputs.';s.className='status danger';return;}
  const body={foundation_group:optimalFoundationGroup,foundation_run_id:optimalFoundationRunId,candidate_id:optimalCandidate.value,robustness_config_name:optimalRobustnessConfig.value,decision_policy:policy,hybrid_validation_output_step_s:Number(optimalHybridStep.value),screening_bracket_padding_steps:Number(optimalBracketPadding.value)};
  s.textContent='Running numerical authority + paired robustness + decision… / Выполняется…';s.className='status';
  const r=await fetch('/api/optimal-operations/decision-runs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const d=await r.json();
  if(!r.ok){s.textContent=d.detail||'Decision run failed';s.className='status danger';return;}
  s.textContent='Decision completed / Решение завершено.';s.className='status ok';renderOptimalStudy(d);optLinks('optimalDecisionLinks',d.artifacts);
}
"""


class PreviewOptimalFoundationHttpRequest(BaseModel):
    design_scenario_name: str
    validation_scenario_name: str
    profile: PreviewOptimalOperationsStudyProfile


class PreviewOptimalDecisionHttpRequest(BaseModel):
    foundation_group: str
    foundation_run_id: str
    candidate_id: str
    robustness_config_name: str
    decision_policy: PreviewOperationalDecisionPolicy
    hybrid_validation_output_step_s: float = Field(gt=0.0)
    screening_bracket_padding_steps: int = Field(ge=0)


def _artifact_urls(group: str, run_id: str, names: set[str] | dict[str, str]) -> dict[str, str]:
    return {name: f"/api/optimal-operations-results/{group}/{run_id}/{name}" for name in names}


def render_preview_page_for_test() -> str:
    page = render_workflow_page().replace("Engineering Preview 0.1.5", f"Engineering Preview {PREVIEW_VERSION}")
    page = page.replace("</section></main>", f"{_OPTIMAL_CARD}</section></main>", 1)
    page = page.replace(
        "bootstrap().catch(e=>setStatus(String(e),'danger'));",
        f"{_OPTIMAL_SCRIPT}\nconst optimalBootstrap=bootstrap;bootstrap=async function(){{await optimalBootstrap();populateOptimalInputs();}};bootstrap().catch(e=>setStatus(String(e),'danger'));",
        1,
    )
    return page


def _remove_route(app: FastAPI, path: str) -> None:
    app.router.routes[:] = [route for route in app.router.routes if getattr(route, "path", None) != path]


def create_preview_app(scenario_root: Path = Path("scenarios"), output_root: Path = Path("runs")) -> FastAPI:
    app = create_workflow_preview_app(scenario_root, output_root)
    app.version = PREVIEW_VERSION
    _remove_route(app, "/")
    _remove_route(app, "/health")

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        return HTMLResponse(render_preview_page_for_test())

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "preview": PREVIEW_VERSION}

    @app.post("/api/optimal-operations/foundation-runs")
    def optimal_foundation(request: PreviewOptimalFoundationHttpRequest) -> dict[str, object]:
        try:
            result = run_preview_optimal_operations_foundation_release(
                scenario_root,
                output_root,
                design_scenario_name=request.design_scenario_name,
                validation_scenario_name=request.validation_scenario_name,
                profile=request.profile,
            )
            group, run_id = _relative_run(output_root, Path(result.artifacts.run_dir))
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "preview": PREVIEW_VERSION,
            "foundation_group": group,
            "foundation_run_id": run_id,
            "preflight": result.foundation.preflight.model_dump(mode="json"),
            "baselines": [item.strategy.model_dump(mode="json") for item in result.foundation.baselines],
            "candidates": [item.model_dump(mode="json") for item in result.foundation.screening.candidates],
            "screening_pareto_candidate_ids": list(result.foundation.screening.pareto_candidate_ids),
            "release_inputs_sha256": result.release_inputs_sha256,
            "artifacts": _artifact_urls(group, run_id, _OPTIMAL_FOUNDATION_ARTIFACTS),
        }

    @app.post("/api/optimal-operations/decision-runs")
    def optimal_decision(request: PreviewOptimalDecisionHttpRequest) -> dict[str, object]:
        try:
            _workflow_config(scenario_root, request.robustness_config_name, "robustness_campaign_config")
            result = run_preview_optimal_operations_decision_release(
                scenario_root,
                output_root,
                foundation_group=request.foundation_group,
                foundation_run_id=request.foundation_run_id,
                candidate_id=request.candidate_id,
                robustness_config_name=request.robustness_config_name,
                decision_policy=request.decision_policy,
                hybrid_validation_output_step_s=request.hybrid_validation_output_step_s,
                screening_bracket_padding_steps=request.screening_bracket_padding_steps,
            )
            authority_group, authority_run = _relative_run(output_root, Path(result.authority_artifacts.run_dir))
            decision_group, decision_run = _relative_run(output_root, Path(result.decision_artifacts.run_dir))
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        artifacts = {
            **_artifact_urls(authority_group, authority_run, _OPTIMAL_AUTHORITY_ARTIFACTS),
            **_artifact_urls(decision_group, decision_run, _OPTIMAL_DECISION_ARTIFACTS),
        }
        return {
            "preview": PREVIEW_VERSION,
            "study": result.decision.study.model_dump(mode="json"),
            "credible_pareto_strategy_ids": list(result.decision.credible_pareto_strategy_ids),
            "recommendation_strategy_id": result.decision.study.recommendation_strategy_id,
            "decision_evidence_sha256": result.decision.decision_evidence_sha256,
            "paired_robustness_semantics": result.paired_robustness.semantics,
            "common_campaign_id": result.paired_robustness.campaign_id,
            "common_sampling_model_sha256": result.paired_robustness.sampling_model_sha256,
            "artifacts": artifacts,
        }

    @app.get("/api/optimal-operations-results/{group}/{run_id}/{name}", response_class=FileResponse)
    def optimal_artifact(group: str, run_id: str, name: str) -> FileResponse:
        media_type = _OPTIMAL_ARTIFACTS.get(name)
        if media_type is None:
            raise HTTPException(status_code=404, detail="Optimal-operations artifact is not exposed by Preview")
        try:
            path = _safe_result_file(output_root, group, run_id, name)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return FileResponse(path, media_type=media_type)

    return app


app = create_preview_app()
