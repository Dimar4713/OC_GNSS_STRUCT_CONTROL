from __future__ import annotations

import base64
import binascii
import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from constellation_control.adapters.spacecraft_workbook import load_spacecraft_workbook
from constellation_control.application.run import load_scenario
from constellation_control.domain.models import ScenarioConfig


class PreviewWorkbookRequest(BaseModel):
    scenario_name: str
    filename: str
    content_base64: str


def _safe_scenario_path(scenario_root: Path, scenario_name: str) -> Path:
    if not scenario_name or Path(scenario_name).name != scenario_name:
        raise ValueError("scenario_name must be a YAML file name without path components")
    root = scenario_root.resolve()
    candidate = (root / scenario_name).resolve()
    if candidate.parent != root or not candidate.is_file():
        raise ValueError(f"scenario not found: {scenario_name}")
    return candidate


def _decode_workbook(request: PreviewWorkbookRequest) -> bytes:
    filename = request.filename.strip()
    if not filename or Path(filename).name != filename:
        raise ValueError("workbook filename must not contain path components")
    suffix = Path(filename).suffix.lower()
    if suffix not in {".xls", ".xlsx"}:
        raise ValueError("workbook must use .xls or .xlsx")
    try:
        raw = base64.b64decode(request.content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("workbook payload is not valid base64") from exc
    if not raw:
        raise ValueError("workbook is empty")
    if len(raw) > 20 * 1024 * 1024:
        raise ValueError("workbook exceeds 20 MiB preview limit")
    return raw


def _attach_for_validation(scenario: ScenarioConfig, digital_twin_payload: dict[str, object]) -> ScenarioConfig:
    payload = scenario.model_dump(mode="json")
    payload["digital_twin"] = digital_twin_payload
    return ScenarioConfig.model_validate(payload)


def preview_workbook(scenario_root: Path, request: PreviewWorkbookRequest) -> dict[str, object]:
    scenario_path = _safe_scenario_path(scenario_root, request.scenario_name)
    scenario = load_scenario(scenario_path)
    raw = _decode_workbook(request)
    suffix = Path(request.filename).suffix.lower()

    with tempfile.TemporaryDirectory(prefix="oc-gnss-workbook-") as tmp:
        workbook_path = Path(tmp) / f"upload{suffix}"
        workbook_path.write_bytes(raw)
        digital_twin = load_spacecraft_workbook(workbook_path)

    validated = _attach_for_validation(scenario, digital_twin.model_dump(mode="json"))
    states = [
        {
            "satellite_id": state.satellite_id,
            "spacecraft_model_id": state.spacecraft_model_id,
            "dry_mass_kg": state.dry_mass_kg,
            "current_propellant_mass_kg": state.current_propellant_mass_kg,
            "current_mass_kg": state.resolved_current_mass_kg,
            "propellant_capacity_kg": state.propellant_capacity_kg,
            "propulsion_system_type": state.propulsion.system_type if state.propulsion else None,
            "propulsion_model_id": state.propulsion.model_id if state.propulsion else None,
            "isp_s": state.propulsion.isp_s if state.propulsion else None,
            "correction_system_type": state.correction_system.system_type if state.correction_system else None,
        }
        for state in digital_twin.spacecraft_states
    ]
    return {
        "valid": True,
        "scenario_name": request.scenario_name,
        "scenario_id": validated.scenario_id,
        "source_config_hash": scenario.config_hash(),
        "candidate_config_hash": validated.config_hash(),
        "spacecraft_count": len(states),
        "group_count": len(digital_twin.groups),
        "spacecraft_states": states,
        "groups": [group.model_dump(mode="json") for group in digital_twin.groups],
        "digital_twin": digital_twin.model_dump(mode="json"),
    }


WORKBOOK_CARD = r"""
<div class="card" id="workbookImportCard">
  <h3>Состояние КА из XLS/XLSX / Spacecraft state workbook</h3>
  <p class="hint">Выберите таблицу с листом Spacecraft_State. Данные сначала проверяются против выбранного сценария; исходный YAML не изменяется. / Select a workbook containing Spacecraft_State. Data are validated against the selected scenario first; the source YAML is not modified.</p>
  <input id="spacecraftWorkbook" type="file" accept=".xls,.xlsx">
  <button onclick="previewSpacecraftWorkbook()">Проверить и показать / Validate and preview</button>
  <div id="workbookStatus" class="status">Файл не выбран / No workbook selected.</div>
  <div id="workbookSummary" class="table-wrap"></div>
</div>
"""


WORKBOOK_SCRIPT = r"""
function workbookMessage(text,kind=''){const e=document.getElementById('workbookStatus');e.textContent=text;e.className='status '+kind;}
function workbookDataUrl(file){return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result));reader.onerror=()=>reject(reader.error);reader.readAsDataURL(file);});}
function renderWorkbookPreview(d){
  const rows=d.spacecraft_states.map(s=>`<tr><td>${s.satellite_id}</td><td>${s.spacecraft_model_id??''}</td><td>${s.dry_mass_kg}</td><td>${s.current_propellant_mass_kg}</td><td>${s.current_mass_kg}</td><td>${s.propulsion_system_type??''}</td><td>${s.isp_s??''}</td><td>${s.correction_system_type??''}</td></tr>`).join('');
  document.getElementById('workbookSummary').innerHTML=`<p><b>КА / spacecraft:</b> ${d.spacecraft_count}; <b>группы / groups:</b> ${d.group_count}</p><p class="hint">Source hash: ${d.source_config_hash}<br>Candidate hash: ${d.candidate_config_hash}</p><table><thead><tr><th>КА</th><th>Модель</th><th>Сухая масса, кг</th><th>Топливо, кг</th><th>Текущая масса, кг</th><th>Двигатель</th><th>Isp, s</th><th>Система коррекции</th></tr></thead><tbody>${rows}</tbody></table>`;
}
async function previewSpacecraftWorkbook(){
  const input=document.getElementById('spacecraftWorkbook');
  const file=input.files&&input.files[0];
  if(!file){workbookMessage('Выберите XLS/XLSX / Select an XLS/XLSX file','danger');return;}
  const scenarioName=scenario.value;
  if(!scenarioName){workbookMessage('Сначала выберите сценарий / Select a scenario first','danger');return;}
  workbookMessage('Проверка таблицы… / Validating workbook…');
  try{
    const dataUrl=await workbookDataUrl(file);
    const marker='base64,';
    const pos=dataUrl.indexOf(marker);
    if(pos<0)throw new Error('Browser did not produce base64 payload');
    const r=await fetch('/api/workbook/preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({scenario_name:scenarioName,filename:file.name,content_base64:dataUrl.slice(pos+marker.length)})});
    const d=await r.json();
    if(!r.ok){workbookMessage(d.detail||'Workbook validation failed','danger');return;}
    renderWorkbookPreview(d);
    workbookMessage('VALID: таблица совместима с выбранным сценарием / workbook is compatible with selected scenario','ok');
  }catch(e){workbookMessage(String(e),'danger');}
}
"""


def install_workbook_preview_route(app: FastAPI, scenario_root: Path) -> None:
    @app.post("/api/workbook/preview")
    def preview_workbook_route(request: PreviewWorkbookRequest) -> dict[str, object]:
        try:
            return preview_workbook(scenario_root, request)
        except (ValueError, TypeError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
