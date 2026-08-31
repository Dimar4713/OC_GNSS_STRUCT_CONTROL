from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from constellation_control.preview.base_preview_shell import (
    _load_preview_scenario,
    _page as base_preview_page,
    _safe_result_file,
    create_preview_app as create_base_preview_app,
)
from constellation_control.preview.closed_loop import PreviewClosedLoopProfile, run_preview_closed_loop

PREVIEW_VERSION = "0.1.5"

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

_CLOSED_LOOP_CARD = r"""
<div class="card" id="closedLoopCard">
  <h3>Замкнутый контур управления / Closed-loop control</h3>
  <p class="hint">P2: NO CONTROL / RETURN-TO-CENTER / BOUNDARY-TO-BOUNDARY. Δu = M+ω; это не оскулирующий аргумент широты. / P2: NO CONTROL / RETURN-TO-CENTER / BOUNDARY-TO-BOUNDARY. Δu = M+ω; this is not osculating argument of latitude.</p>
  <div id="closedLoopContext" class="status">Выберите сценарий / Select a scenario.</div>
  <label for="closedLoopPolicy"><b>Политика / Policy</b></label>
  <select id="closedLoopPolicy">
    <option value="no_control">NO CONTROL</option>
    <option value="return_to_center">RETURN-TO-CENTER</option>
    <option value="boundary_to_boundary">BOUNDARY-TO-BOUNDARY</option>
  </select>
  <label for="closedLoopProfile"><b>Явный control profile JSON / Explicit control profile JSON</b></label>
  <textarea id="closedLoopProfile" rows="15" style="width:100%;box-sizing:border-box;margin-top:8px" placeholder="Required explicit fields: campaign_horizon_s, coast_horizon_s, coast_output_step_s, max_corrections, authority_times_s, maneuver_windows, max_abs_impulse_rtn_m_s, min_impulse_bit_m_s, trust_tolerances_roe, target_roe, w_tracking, w_max. No control values are prefilled by Preview."></textarea>
  <p class="hint">Все управляющие числа должны быть введены оператором или загружены как явный JSON-профиль. Preview не подставляет impulse/MIB/trust/target/weights/horizon/grid. / Every control number must be operator-supplied or loaded as explicit JSON. Preview injects no impulse/MIB/trust/target/weight/horizon/grid defaults.</p>
  <button id="closedLoopRunBtn" onclick="runClosedLoop()">Запустить closed-loop / Run closed-loop</button>
  <div id="closedLoopStatus" class="status">Профиль не задан / Profile not supplied.</div>
  <div id="closedLoopResults"></div>
  <div id="closedLoopArtifacts" class="oplinks"></div>
</div>
"""

_CLOSED_LOOP_SCRIPT = r"""
function closedLoopEsc(v){return String(v).replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[c]));}
function closedLoopFmt(v){return v===null||v===undefined?'—':String(v);}
function renderClosedLoopContext(){
  const el=document.getElementById('closedLoopContext');
  if(!el)return;
  if(!current){el.textContent='Выберите сценарий / Select a scenario.';return;}
  const c=(current.normalized&&current.normalized.constraints)||{};
  el.innerHTML='<b>Authority / Ограничения:</b><br>'+ 'mode='+closedLoopEsc(current.force_mode)+'; frame='+closedLoopEsc(current.frame)+'; time='+closedLoopEsc(current.time_scale)+'<br>'+ 'force fingerprint=<code>'+closedLoopEsc(current.force_model_fingerprint)+'</code><br>'+ 'phase corridor='+closedLoopEsc(closedLoopFmt(c.phase_corridor_rad))+' rad; '+ 'fleet min distance='+closedLoopEsc(closedLoopFmt(c.min_pair_distance_m))+' m; '+ 'propellant reserve fraction='+closedLoopEsc(closedLoopFmt(c.propellant_reserve_fraction));
}
function renderClosedLoopResult(d){
  const c=d.campaign,m=d.metrics,a=m.annualized||{};
  let h='<h4>Результат / Result</h4><div class="table-wrap"><table>'+ '<tr><th>Показатель / Metric</th><th>Evidence value</th></tr>'+ '<tr><td>Policy / Политика</td><td>'+closedLoopEsc(c.policy)+'</td></tr>'+ '<tr><td>Termination / Завершение</td><td>'+closedLoopEsc(c.termination_reason)+'</td></tr>'+ '<tr><td>Corrections / Коррекции</td><td>'+closedLoopEsc(c.correction_count)+'</td></tr>'+ '<tr><td>Authority attempts / Попытки authority</td><td>'+closedLoopEsc(c.authority_attempt_count)+'</td></tr>'+ '<tr><td>Cumulative ΔV, m/s</td><td>'+closedLoopEsc(c.cumulative_delta_v_m_s)+'</td></tr>'+ '<tr><td>Propellant used, kg / Топливо израсходовано</td><td>'+closedLoopEsc(c.cumulative_propellant_used_kg)+'</td></tr>'+ '<tr><td>Propellant remaining, kg / Остаток</td><td>'+closedLoopEsc(c.propellant_remaining_kg)+'</td></tr>'+ '<tr><td>Required reserve, kg / Резерв</td><td>'+closedLoopEsc(c.required_reserve_kg)+'</td></tr>'+ '<tr><td>Annualization available / Годовая оценка</td><td>'+closedLoopEsc(a.available)+'</td></tr>'+ '<tr><td>ΔV per Julian year, m/s</td><td>'+closedLoopEsc(closedLoopFmt(a.delta_v_m_s_per_julian_year))+'</td></tr>'+ '<tr><td>Propellant per Julian year, kg</td><td>'+closedLoopEsc(closedLoopFmt(a.propellant_kg_per_julian_year))+'</td></tr>'+ '<tr><td>Lifetime projection available / Прогноз ресурса</td><td>'+closedLoopEsc(a.lifetime_projection_available)+'</td></tr>'+ '<tr><td>Projected years to reserve / Лет до резерва</td><td>'+closedLoopEsc(closedLoopFmt(a.projected_years_to_reserve))+'</td></tr>'+ '<tr><td>Rearm/settling available / Переармирование</td><td>'+closedLoopEsc(m.rearm_settling_available)+'; '+closedLoopEsc(closedLoopFmt(m.rearm_settling_reason))+'</td></tr>'+ '<tr><td>Authority backend(s)</td><td>'+closedLoopEsc((c.authority_backends||[]).join(', ')||'—')+'</td></tr>'+ '<tr><td>Force fingerprint</td><td><code>'+closedLoopEsc(c.force_model_fingerprint)+'</code></td></tr>'+ '<tr><td>Frame / time scale</td><td>'+closedLoopEsc(c.frame)+' / '+closedLoopEsc(c.time_scale)+'</td></tr>'+ '</table></div>';
  if(Array.isArray(d.corrections)&&d.corrections.length){h+='<h4>Коррекции / Corrections</h4><div class="table-wrap"><table><tr><th>#</th><th>t, s</th><th>Reason</th><th>ΔV, m/s</th><th>Fuel, kg</th><th>Remaining, kg</th></tr>';for(const x of d.corrections){h+='<tr><td>'+closedLoopEsc(x.correction_index)+'</td><td>'+closedLoopEsc(x.event_time_s)+'</td><td>'+closedLoopEsc(x.policy_reason)+'</td><td>'+closedLoopEsc(x.delta_v_m_s)+'</td><td>'+closedLoopEsc(x.propellant_used_kg)+'</td><td>'+closedLoopEsc(x.propellant_remaining_kg)+'</td></tr>';}h+='</table></div>';}
  document.getElementById('closedLoopResults').innerHTML=h;
  const links=Object.entries(d.artifacts||{}).map(([name,url])=>'<a target="_blank" href="'+closedLoopEsc(url)+'">'+closedLoopEsc(name)+'</a>');
  document.getElementById('closedLoopArtifacts').innerHTML=links.join(' ');
}
async function runClosedLoop(){
  const status=document.getElementById('closedLoopStatus');
  const n=scenario.value;
  if(!n){status.textContent='Сценарий не выбран / Scenario is not selected.';status.className='status danger';return;}
  const raw=document.getElementById('closedLoopProfile').value.trim();
  if(!raw){status.textContent='Введите явный control profile JSON / Supply an explicit control profile JSON.';status.className='status danger';return;}
  let profile;try{profile=JSON.parse(raw);}catch(e){status.textContent='Некорректный JSON / Invalid JSON: '+String(e);status.className='status danger';return;}
  profile.policy=document.getElementById('closedLoopPolicy').value;
  status.textContent='Выполняется closed-loop расчёт / Running closed-loop campaign…';status.className='status';
  const r=await fetch('/api/closed-loop-runs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({scenario_name:n,profile})});
  const d=await r.json();if(!r.ok){status.textContent=(d.detail||'Closed-loop run failed');status.className='status danger';return;}
  status.textContent='Closed-loop завершён / Closed-loop completed: '+d.run_dir;status.className='status ok';renderClosedLoopResult(d);
}
"""


class PreviewClosedLoopHttpRequest(BaseModel):
    scenario_name: str
    profile: PreviewClosedLoopProfile


def _load_exact_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def render_preview_page_for_test() -> str:
    page = base_preview_page().replace("Engineering Preview 0.1.4", f"Engineering Preview {PREVIEW_VERSION}")
    page = page.replace("</section></main>", f"{_CLOSED_LOOP_CARD}</section></main>", 1)
    page = page.replace("renderPreflight();renderDuration()}}", "renderPreflight();renderDuration();renderClosedLoopContext()}}", 1)
    page = page.replace("bootstrap().catch(e=>setStatus(String(e),'danger'));", f"{_CLOSED_LOOP_SCRIPT}\nbootstrap().catch(e=>setStatus(String(e),'danger'));", 1)
    return page


def _remove_base_route(app: FastAPI, path: str) -> None:
    app.router.routes[:] = [route for route in app.router.routes if getattr(route, "path", None) != path]


def create_preview_app(scenario_root: Path = Path("scenarios"), output_root: Path = Path("runs")) -> FastAPI:
    app = create_base_preview_app(scenario_root, output_root)
    app.version = PREVIEW_VERSION
    _remove_base_route(app, "/")
    _remove_base_route(app, "/health")

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        return HTMLResponse(render_preview_page_for_test())

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "preview": PREVIEW_VERSION}

    @app.post("/api/closed-loop-runs")
    def closed_loop_run(request: PreviewClosedLoopHttpRequest) -> dict[str, object]:
        try:
            safe_path, _ = _load_preview_scenario(scenario_root, request.scenario_name)
            execution = run_preview_closed_loop(safe_path, output_root, request.profile)
            run_dir = Path(execution.run_dir)
            relative = run_dir.resolve().relative_to(output_root.resolve())
            if len(relative.parts) != 2:
                raise RuntimeError("Неожиданная структура каталога closed-loop запуска / unexpected closed-loop run directory layout")
            metrics = _load_exact_json(Path(execution.metrics_path))
            corrections = _load_exact_json(Path(execution.corrections_json_path))
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        scenario_id, run_id = relative.parts
        prefix = f"/api/closed-loop-results/{scenario_id}/{run_id}"
        authority_backends = sorted({attempt.replay_backend for attempt in execution.campaign.authority_attempts if attempt.replay_backend is not None})
        return {
            "run_dir": execution.run_dir,
            "campaign": {
                "policy": execution.campaign.policy.value,
                "termination_reason": execution.campaign.termination_reason,
                "correction_count": execution.campaign.correction_count,
                "authority_attempt_count": len(execution.campaign.authority_attempts),
                "authority_backends": authority_backends,
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
            "artifacts": {name: f"{prefix}/{name}" for name in _CLOSED_LOOP_ARTIFACT_MEDIA_TYPES},
        }

    @app.get("/api/closed-loop-results/{scenario_id}/{run_id}/{name}", response_class=FileResponse)
    def closed_loop_artifact(scenario_id: str, run_id: str, name: str) -> FileResponse:
        media_type = _CLOSED_LOOP_ARTIFACT_MEDIA_TYPES.get(name)
        if media_type is None:
            raise HTTPException(status_code=404, detail="Closed-loop result artifact is not exposed by Preview")
        try:
            path = _safe_result_file(output_root, scenario_id, run_id, name)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return FileResponse(path, media_type=media_type)

    return app


app = create_preview_app()
