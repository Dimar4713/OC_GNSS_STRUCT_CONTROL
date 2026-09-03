from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from constellation_control.adapters.orekit.adapter import orekit_progress_callback
from constellation_control.application.run_duration import DurationRunResult, run_scenario_with_duration
from constellation_control.preview.base_preview_shell import PreviewRunRequest, _load_preview_scenario
from constellation_control.preview.duration import predicted_output_sample_count, resolve_duration_s
from constellation_control.preview.gravity_release_app import (
    create_preview_app as create_gravity_preview_app,
    render_preview_page_for_test as render_gravity_page,
)
from constellation_control.preview.operations import preview_operations_payload
from constellation_control.preview.progress_jobs import PreviewRunJobManager

_JOB_MANAGER = PreviewRunJobManager()

_PROGRESS_CARD = r"""
<div class="card" id="runProgressCard">
  <h3>Ход расчёта / Calculation progress</h3>
  <progress id="runProgressBar" max="100" value="0" style="width:100%"></progress>
  <div id="runProgressText" class="status">Нет активного расчёта / No active calculation.</div>
  <div class="oplinks">
    <a id="keplerDriftReport" target="_blank" style="display:none">Проверка дрейфа Kepler ↔ Orekit / Kepler ↔ Orekit drift consistency</a>
  </div>
</div>
"""

_PROGRESS_SCRIPT = r"""
let activeRunJobId=null,runProgressTimer=null;
function renderRunProgress(d){
  const bar=document.getElementById('runProgressBar'),box=document.getElementById('runProgressText');
  bar.value=Number(d.percent||0);
  const p=d.point_index==null?'':` | point ${d.point_index}/${d.point_total}`;
  const s=d.satellite_id?` | ${d.satellite_id}${d.satellite_index==null?'':` (${d.satellite_index}/${d.satellite_total})`}`:'';
  const t=d.time_s==null?'':` | t=${d.time_s}/${d.duration_s} s`;
  const e=d.epoch?` | epoch=${d.epoch}`:'';
  box.textContent=`${String(d.phase).toUpperCase()}${s}${t}${p}${e} | ${Number(d.percent||0).toFixed(1)} %${d.message?' | '+d.message:''}`;
  box.className='status '+(d.state==='failed'?'danger':d.state==='completed'?'ok':'');
}
async function pollRunProgress(){
  if(!activeRunJobId)return;
  const r=await fetch('/api/run-jobs/'+encodeURIComponent(activeRunJobId));const d=await r.json();
  if(!r.ok){setStatus(d.detail||'Progress status failed','danger');activeRunJobId=null;return;}
  renderRunProgress(d);
  if(d.state==='completed'){
    activeRunJobId=null;runBtn.disabled=false;
    const x=d.result;operations=x.operations;artifactLinks=x.artifacts;renderOperations();
    const drift=document.getElementById('keplerDriftReport');
    if(x.artifacts&&x.artifacts.kepler_drift_consistency){drift.href=x.artifacts.kepler_drift_consistency;drift.style.display='inline-block';}else{drift.removeAttribute('href');drift.style.display='none';}
    durationInfo.textContent=`${tr('duration')}: ${x.duration.duration_s} s; ${tr('step')}: ${x.duration.output_step_s} s; ${tr('samples')}: ${x.duration.predicted_sample_count}. `+tr('unchanged');
    setStatus(tr('completed')+': '+x.run_dir,'ok');result.href=x.report_url;result.textContent=tr('report');return;
  }
  if(d.state==='failed'){
    activeRunJobId=null;runBtn.disabled=false;setStatus(d.error||d.message||tr('runFail'),'danger');return;
  }
  runProgressTimer=setTimeout(pollRunProgress,500);
}
runScenario=async function(){
  const n=scenario.value;if(!n||activeRunJobId)return;
  const p=durationPreset.value;const custom=p==='custom'?Number(customDuration.value):null;
  runBtn.disabled=true;setStatus(tr('running'));
  const r=await fetch('/api/run-jobs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({scenario_name:n,duration_preset:p,custom_duration_s:custom})});const d=await r.json();
  if(!r.ok){runBtn.disabled=false;setStatus(d.detail||tr('runFail'),'danger');return;}
  activeRunJobId=d.job_id;renderRunProgress(d);pollRunProgress();
};
"""


def _result_payload(output_root: Path, execution: DurationRunResult) -> dict[str, object]:
    run_dir = execution.run_dir
    relative = run_dir.resolve().relative_to(output_root.resolve())
    if len(relative.parts) != 2:
        raise RuntimeError("unexpected run directory layout")
    scenario_id, run_id = relative.parts
    prefix = f"/api/results/{scenario_id}/{run_id}"
    artifacts = {
        "phase_plot": f"{prefix}/11_delta_u_mean.png",
        "along_track_plot": f"{prefix}/12_along_track_mean_arc_proxy.png",
        "interactive_phase": f"{prefix}/interactive_delta_u_mean.html",
    }
    if (run_dir / "kepler_drift_consistency.html").is_file():
        artifacts["kepler_drift_consistency"] = f"{prefix}/kepler_drift_consistency.html"
    return {
        "run_dir": str(run_dir),
        "report_url": f"{prefix}/report.html",
        "operations": preview_operations_payload(run_dir),
        "duration": {
            "preset": execution.preset,
            "duration_s": execution.duration_s,
            "output_step_s": execution.output_step_s,
            "predicted_sample_count": execution.predicted_sample_count,
        },
        "artifacts": artifacts,
    }


def render_preview_page_for_test() -> str:
    page = render_gravity_page()
    page = page.replace("</section></main>", f"{_PROGRESS_CARD}</section></main>", 1)
    page = page.replace(
        "bootstrap().catch(e=>setStatus(String(e),'danger'));",
        f"{_PROGRESS_SCRIPT}\nbootstrap().catch(e=>setStatus(String(e),'danger'));",
        1,
    )
    return page


def create_preview_app(scenario_root: Path = Path("scenarios"), output_root: Path = Path("runs")) -> FastAPI:
    app = create_gravity_preview_app(scenario_root, output_root)
    app.router.routes[:] = [route for route in app.router.routes if getattr(route, "path", None) != "/"]

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        return HTMLResponse(render_preview_page_for_test())

    @app.post("/api/run-jobs", status_code=202)
    def start_run_job(request: PreviewRunRequest) -> dict[str, object]:
        try:
            scenario_path, scenario = _load_preview_scenario(scenario_root, request.scenario_name)
            duration_s = resolve_duration_s(
                request.duration_preset,
                request.custom_duration_s,
                scenario_duration_s=scenario.duration_s,
            )
            point_total = predicted_output_sample_count(duration_s, scenario.output_step_s)
            satellite_total = len(scenario.constellation.satellites)

            def worker(update):
                update(
                    phase="propagation",
                    percent=1.0,
                    point_index=1,
                    point_total=point_total,
                    satellite_index=1 if satellite_total else None,
                    satellite_total=satellite_total,
                    satellite_id=scenario.constellation.satellites[0].satellite_id if satellite_total else None,
                    time_s=0.0,
                    epoch=scenario.epoch.isoformat(),
                    message="starting authoritative propagation",
                )
                with orekit_progress_callback(lambda payload: update(**payload)):
                    execution = run_scenario_with_duration(
                        scenario_path,
                        output_root,
                        preset=request.duration_preset,
                        custom_duration_s=request.custom_duration_s,
                    )
                update(
                    phase="post_processing",
                    percent=95.0,
                    point_index=point_total,
                    point_total=point_total,
                    satellite_index=satellite_total if satellite_total else None,
                    satellite_total=satellite_total,
                    satellite_id=scenario.constellation.satellites[-1].satellite_id if satellite_total else None,
                    time_s=duration_s,
                    message="propagation completed; post-processing results",
                )
                return _result_payload(output_root, execution)

            snapshot = _JOB_MANAGER.start(
                scenario_name=request.scenario_name,
                duration_s=duration_s,
                output_step_s=scenario.output_step_s,
                worker=worker,
            )
            return snapshot.payload()
        except Exception as exc:  # noqa: BLE001 - API boundary is fail-closed
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/run-jobs/{job_id}")
    def run_job_status(job_id: str) -> dict[str, object]:
        snapshot = _JOB_MANAGER.get(job_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="run job not found")
        return snapshot.payload()

    return app
