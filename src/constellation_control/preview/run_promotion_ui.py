from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from constellation_control.application.acceptance_evidence import export_completed_run_acceptance_evidence
from constellation_control.application.run_promotion import list_promotable_runs, promote_completed_run


class PromoteRunRequest(BaseModel):
    scenario_id: str
    run_id: str
    target_scenario_name: str
    new_scenario_id: str


class ExportAcceptanceEvidenceRequest(BaseModel):
    scenario_id: str
    run_id: str


RUN_PROMOTION_CARD = r"""
<div class="card" id="runPromotionCard">
  <h3>Продолжить завершённый расчёт / Promote completed run</h3>
  <p class="hint">Создаёт новый runnable ScenarioConfig только из полного сохранённого propagation evidence. Расчёт повторно не запускается. / Creates a runnable continuation ScenarioConfig only from complete persisted propagation evidence. No propagation rerun is performed.</p>
  <label for="promotableRun"><b>Завершённый расчёт / Completed run</b></label>
  <select id="promotableRun"></select>
  <button onclick="refreshPromotableRuns()">Обновить список / Refresh</button>
  <label for="promotionScenarioId"><b>Новый scenario_id / New scenario_id</b></label>
  <input id="promotionScenarioId" type="text" placeholder="continued-scenario-id">
  <label for="promotionScenarioName"><b>Новый YAML / New YAML</b></label>
  <input id="promotionScenarioName" type="text" placeholder="continued-scenario.yaml">
  <button onclick="promoteCompletedRun()">Создать продолжение / Create continuation</button>
  <div id="runPromotionStatus" class="status">Доступны только runs с полным propagation evidence / Only runs with complete propagation evidence are listed.</div>
  <hr>
  <h4>Canonical acceptance evidence</h4>
  <p class="hint">Экспортирует выбранный completed run как неизменяемый ZIP с SHA-256 manifest. Требует независимый Kepler ↔ Orekit drift diagnostic; ничего не пересчитывает и не восстанавливает. / Exports the selected completed run as an immutable checksummed ZIP. Requires the independent Kepler ↔ Orekit drift diagnostic; no values are rerun or reconstructed.</p>
  <button id="exportAcceptanceEvidenceButton" onclick="exportAcceptanceEvidence()">Экспортировать evidence ZIP / Export evidence ZIP</button>
  <div id="acceptanceEvidenceStatus" class="status">Для #171 используйте реальный GLONASS run; synthetic run не заменяет authoritative acceptance. / Use a real GLONASS run for #171; a synthetic run is not authoritative acceptance.</div>
  <div id="acceptanceEvidenceLink"></div>
</div>
"""


RUN_PROMOTION_SCRIPT = r"""
function promotionStatus(text,kind=''){const e=document.getElementById('runPromotionStatus');e.textContent=text;e.className='status '+kind;}
function evidenceStatus(text,kind=''){const e=document.getElementById('acceptanceEvidenceStatus');e.textContent=text;e.className='status '+kind;}
async function refreshPromotableRuns(){
  const r=await fetch('/api/promotable-runs');const d=await r.json();
  if(!r.ok){promotionStatus(d.detail||'Cannot list promotable runs','danger');return;}
  const sel=document.getElementById('promotableRun');sel.replaceChildren();
  for(const item of d.runs||[]){
    const o=document.createElement('option');
    o.value=item.scenario_id+'|'+item.run_id;
    o.textContent=item.scenario_id+' | '+item.run_id+' | '+item.backend+' | '+item.epoch;
    sel.appendChild(o);
  }
  if(!sel.options.length){promotionStatus('Нет promotable runs: выполните новый успешный расчёт с propagation_result.json / No promotable runs yet.','');return;}
  promotionStatus('Найдено promotable runs: '+sel.options.length+' / Promotable runs: '+sel.options.length,'ok');
}
async function promoteCompletedRun(){
  const sel=document.getElementById('promotableRun');
  if(!sel.value){promotionStatus('Выберите завершённый расчёт / Select a completed run','danger');return;}
  const [scenarioId,runId]=sel.value.split('|');
  const target=document.getElementById('promotionScenarioName').value.trim();
  const newId=document.getElementById('promotionScenarioId').value.trim();
  if(!target||!newId){promotionStatus('Укажите новый scenario_id и YAML / Supply new scenario_id and YAML','danger');return;}
  promotionStatus('Проверка evidence и создание continuation… / Validating evidence and creating continuation…');
  const r=await fetch('/api/promotable-runs/promote',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({scenario_id:scenarioId,run_id:runId,target_scenario_name:target,new_scenario_id:newId})});
  const d=await r.json();
  if(!r.ok){promotionStatus(d.detail||'Promotion failed','danger');return;}
  const c=await fetch('/api/scenarios');catalog=await c.json();
  scenario.replaceChildren(...catalog.scenarios.map(x=>{const o=document.createElement('option');o.value=x;o.textContent=x;return o;}));
  scenario.value=d.scenario_name;
  await loadScenario();
  promotionStatus('Создано продолжение: '+d.scenario_name+'; epoch='+d.epoch+' / Continuation created','ok');
}
async function exportAcceptanceEvidence(){
  const sel=document.getElementById('promotableRun');
  if(!sel.value){evidenceStatus('Выберите завершённый расчёт / Select a completed run','danger');return;}
  const [scenarioId,runId]=sel.value.split('|');
  evidenceStatus('Проверка authority и упаковка evidence… / Validating authority and packaging evidence…');
  document.getElementById('acceptanceEvidenceLink').replaceChildren();
  const r=await fetch('/api/acceptance-evidence/export',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({scenario_id:scenarioId,run_id:runId})});
  const d=await r.json();
  if(!r.ok){evidenceStatus(d.detail||'Evidence export failed','danger');return;}
  evidenceStatus('Evidence готов: '+d.package_id+'; ZIP SHA-256='+d.zip_sha256,'ok');
  const a=document.createElement('a');a.href=d.download_url;a.textContent='Скачать evidence ZIP / Download evidence ZIP';a.setAttribute('download',d.zip_name);document.getElementById('acceptanceEvidenceLink').appendChild(a);
}
"""


def _safe_evidence_zip(output_root: Path, zip_name: str) -> Path:
    if not zip_name or Path(zip_name).name != zip_name or not zip_name.endswith(".zip"):
        raise ValueError("invalid evidence ZIP name")
    root = (output_root.resolve() / "acceptance-evidence").resolve()
    candidate = (root / zip_name).resolve()
    if candidate.parent != root or not candidate.is_file():
        raise ValueError("acceptance evidence ZIP not found")
    return candidate


def install_run_promotion_routes(app: FastAPI, scenario_root: Path, output_root: Path) -> None:
    @app.get('/api/promotable-runs')
    def promotable_runs() -> dict[str, object]:
        try:
            return {'runs': list_promotable_runs(output_root)}
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post('/api/promotable-runs/promote')
    def promote_run(request: PromoteRunRequest) -> dict[str, object]:
        try:
            return promote_completed_run(
                scenario_root,
                output_root,
                scenario_id=request.scenario_id,
                run_id=request.run_id,
                target_scenario_name=request.target_scenario_name,
                new_scenario_id=request.new_scenario_id,
            )
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post('/api/acceptance-evidence/export')
    def export_acceptance_evidence(request: ExportAcceptanceEvidenceRequest) -> dict[str, object]:
        try:
            result = export_completed_run_acceptance_evidence(
                output_root,
                scenario_id=request.scenario_id,
                run_id=request.run_id,
            )
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "package_id": result["package_id"],
            "zip_name": result["zip_name"],
            "zip_sha256": result["zip_sha256"],
            "download_url": f"/api/acceptance-evidence/{result['zip_name']}",
        }

    @app.get('/api/acceptance-evidence/{zip_name}')
    def download_acceptance_evidence(zip_name: str) -> FileResponse:
        try:
            path = _safe_evidence_zip(output_root, zip_name)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return FileResponse(path, media_type="application/zip", filename=path.name)
