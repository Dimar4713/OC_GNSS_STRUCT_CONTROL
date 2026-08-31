from __future__ import annotations

import base64
import binascii
import tempfile
from pathlib import Path

import yaml
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from constellation_control.adapters.spacecraft_workbook import load_spacecraft_workbook
from constellation_control.application.run import load_scenario
from constellation_control.domain.digital_twin import DigitalTwinConfig, ScenarioLineage
from constellation_control.domain.models import ScenarioConfig


class PreviewWorkbookRequest(BaseModel):
    scenario_name: str
    filename: str
    content_base64: str


class ApplyWorkbookRequest(PreviewWorkbookRequest):
    derived_scenario_name: str
    derived_scenario_id: str


def _safe_scenario_path(scenario_root: Path, scenario_name: str) -> Path:
    if not scenario_name or Path(scenario_name).name != scenario_name:
        raise ValueError("scenario_name must be a YAML file name without path components")
    root = scenario_root.resolve()
    candidate = (root / scenario_name).resolve()
    if candidate.parent != root or not candidate.is_file():
        raise ValueError(f"scenario not found: {scenario_name}")
    return candidate


def _safe_new_scenario_path(scenario_root: Path, scenario_name: str) -> Path:
    if not scenario_name or Path(scenario_name).name != scenario_name:
        raise ValueError("derived_scenario_name must be a YAML file name without path components")
    if not scenario_name.lower().endswith((".yaml", ".yml")):
        raise ValueError("derived scenario must use .yaml or .yml")
    root = scenario_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    candidate = (root / scenario_name).resolve()
    if candidate.parent != root:
        raise ValueError("invalid derived scenario path")
    if candidate.exists():
        raise ValueError("derived scenario file already exists; existing scenarios are never overwritten")
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


def _load_uploaded_digital_twin(request: PreviewWorkbookRequest) -> DigitalTwinConfig:
    raw = _decode_workbook(request)
    suffix = Path(request.filename).suffix.lower()
    with tempfile.TemporaryDirectory(prefix="oc-gnss-workbook-") as tmp:
        workbook_path = Path(tmp) / f"upload{suffix}"
        workbook_path.write_bytes(raw)
        return load_spacecraft_workbook(workbook_path)


def _merge_digital_twin(
    scenario: ScenarioConfig,
    imported: DigitalTwinConfig,
    lineage: ScenarioLineage | None = None,
) -> DigitalTwinConfig:
    existing = scenario.digital_twin
    return DigitalTwinConfig(
        spacecraft_states=imported.spacecraft_states,
        groups=imported.groups,
        perturbations=existing.perturbations if existing is not None else (),
        lineage=lineage if lineage is not None else (existing.lineage if existing is not None else None),
    )


def _attach_for_validation(scenario: ScenarioConfig, digital_twin: DigitalTwinConfig) -> ScenarioConfig:
    payload = scenario.model_dump(mode="json")
    payload["digital_twin"] = digital_twin.model_dump(mode="json")
    return ScenarioConfig.model_validate(payload)


def preview_workbook(scenario_root: Path, request: PreviewWorkbookRequest) -> dict[str, object]:
    scenario_path = _safe_scenario_path(scenario_root, request.scenario_name)
    scenario = load_scenario(scenario_path)
    imported = _load_uploaded_digital_twin(request)
    digital_twin = _merge_digital_twin(scenario, imported)
    validated = _attach_for_validation(scenario, digital_twin)
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
        for state in imported.spacecraft_states
    ]
    return {
        "valid": True,
        "scenario_name": request.scenario_name,
        "scenario_id": validated.scenario_id,
        "source_config_hash": scenario.config_hash(),
        "candidate_config_hash": validated.config_hash(),
        "spacecraft_count": len(states),
        "group_count": len(imported.groups),
        "spacecraft_states": states,
        "groups": [group.model_dump(mode="json") for group in imported.groups],
        "digital_twin": digital_twin.model_dump(mode="json"),
    }


def apply_workbook_as_derived(scenario_root: Path, request: ApplyWorkbookRequest) -> dict[str, object]:
    scenario_path = _safe_scenario_path(scenario_root, request.scenario_name)
    parent = load_scenario(scenario_path)
    child_id = request.derived_scenario_id.strip()
    if not child_id:
        raise ValueError("derived_scenario_id must not be empty")
    if child_id == parent.scenario_id:
        raise ValueError("derived_scenario_id must differ from parent scenario_id")
    target = _safe_new_scenario_path(scenario_root, request.derived_scenario_name)

    imported = _load_uploaded_digital_twin(request)
    lineage = ScenarioLineage(
        parent_scenario_id=parent.scenario_id,
        parent_config_hash=parent.config_hash(),
        transformation="import",
        random_seed=None,
    )
    digital_twin = _merge_digital_twin(parent, imported, lineage=lineage)
    payload = parent.model_dump(mode="json")
    payload["scenario_id"] = child_id
    payload["digital_twin"] = digital_twin.model_dump(mode="json")
    child = ScenarioConfig.model_validate(payload)

    text = yaml.safe_dump(child.model_dump(mode="json"), sort_keys=False, allow_unicode=True)
    target.write_text(text, encoding="utf-8")
    return {
        "saved": True,
        "scenario_name": target.name,
        "scenario_id": child.scenario_id,
        "parent_scenario_name": request.scenario_name,
        "parent_scenario_id": parent.scenario_id,
        "parent_config_hash": parent.config_hash(),
        "child_config_hash": child.config_hash(),
        "lineage": lineage.model_dump(mode="json"),
    }


WORKBOOK_CARD = r"""
<div class="card" id="workbookImportCard">
  <h3>Состояние КА из XLS/XLSX / Spacecraft state workbook</h3>
  <p class="hint">Выберите таблицу с листом Spacecraft_State. Данные сначала проверяются против выбранного сценария; исходный YAML не изменяется. / Select a workbook containing Spacecraft_State. Data are validated against the selected scenario first; the source YAML is not modified.</p>
  <input id="spacecraftWorkbook" type="file" accept=".xls,.xlsx">
  <button onclick="previewSpacecraftWorkbook()">Проверить и показать / Validate and preview</button>
  <div id="workbookStatus" class="status">Файл не выбран / No workbook selected.</div>
  <div id="workbookSummary" class="table-wrap"></div>
  <label for="derivedWorkbookScenarioId"><b>Новый scenario_id / New scenario_id</b></label>
  <input id="derivedWorkbookScenarioId" type="text" placeholder="my-derived-scenario">
  <label for="derivedWorkbookScenarioName"><b>Сохранить как новый YAML / Save as new YAML</b></label>
  <input id="derivedWorkbookScenarioName" type="text" placeholder="my-derived-scenario.yaml">
  <button onclick="applySpacecraftWorkbook()">Применить как производный сценарий / Apply as derived scenario</button>
</div>
"""


WORKBOOK_SCRIPT = r"""
function workbookMessage(text,kind=''){const e=document.getElementById('workbookStatus');e.textContent=text;e.className='status '+kind;}
function workbookDataUrl(file){return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result));reader.onerror=()=>reject(reader.error);reader.readAsDataURL(file);});}
async function workbookPayload(){
  const input=document.getElementById('spacecraftWorkbook');
  const file=input.files&&input.files[0];
  if(!file)throw new Error('Выберите XLS/XLSX / Select an XLS/XLSX file');
  const scenarioName=scenario.value;
  if(!scenarioName)throw new Error('Сначала выберите сценарий / Select a scenario first');
  const dataUrl=await workbookDataUrl(file);
  const marker='base64,';
  const pos=dataUrl.indexOf(marker);
  if(pos<0)throw new Error('Browser did not produce base64 payload');
  return {scenario_name:scenarioName,filename:file.name,content_base64:dataUrl.slice(pos+marker.length)};
}
function renderWorkbookPreview(d){
  const rows=d.spacecraft_states.map(s=>`<tr><td>${s.satellite_id}</td><td>${s.spacecraft_model_id??''}</td><td>${s.dry_mass_kg}</td><td>${s.current_propellant_mass_kg}</td><td>${s.current_mass_kg}</td><td>${s.propulsion_system_type??''}</td><td>${s.isp_s??''}</td><td>${s.correction_system_type??''}</td></tr>`).join('');
  document.getElementById('workbookSummary').innerHTML=`<p><b>КА / spacecraft:</b> ${d.spacecraft_count}; <b>группы / groups:</b> ${d.group_count}</p><p class="hint">Source hash: ${d.source_config_hash}<br>Candidate hash: ${d.candidate_config_hash}</p><table><thead><tr><th>КА</th><th>Модель</th><th>Сухая масса, кг</th><th>Топливо, кг</th><th>Текущая масса, кг</th><th>Двигатель</th><th>Isp, s</th><th>Система коррекции</th></tr></thead><tbody>${rows}</tbody></table>`;
  const source=scenario.value||'scenario.yaml';
  const lower=source.toLowerCase();
  const ext=lower.endsWith('.yml')?'.yml':'.yaml';
  const stem=source.slice(0,source.length-ext.length);
  document.getElementById('derivedWorkbookScenarioName').value=stem+'-workbook'+ext;
  document.getElementById('derivedWorkbookScenarioId').value=d.scenario_id+'-workbook';
}
async function previewSpacecraftWorkbook(){
  workbookMessage('Проверка таблицы… / Validating workbook…');
  try{
    const payload=await workbookPayload();
    const r=await fetch('/api/workbook/preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    const d=await r.json();
    if(!r.ok){workbookMessage(d.detail||'Workbook validation failed','danger');return;}
    renderWorkbookPreview(d);
    workbookMessage('VALID: таблица совместима с выбранным сценарием / workbook is compatible with selected scenario','ok');
  }catch(e){workbookMessage(String(e),'danger');}
}
async function applySpacecraftWorkbook(){
  workbookMessage('Повторная проверка и создание производного сценария… / Revalidating and creating derived scenario…');
  try{
    const payload=await workbookPayload();
    payload.derived_scenario_id=document.getElementById('derivedWorkbookScenarioId').value.trim();
    payload.derived_scenario_name=document.getElementById('derivedWorkbookScenarioName').value.trim();
    if(!payload.derived_scenario_id||!payload.derived_scenario_name)throw new Error('Укажите новый scenario_id и имя YAML / Supply new scenario_id and YAML name');
    const r=await fetch('/api/workbook/apply-derived',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    const d=await r.json();
    if(!r.ok){workbookMessage(d.detail||'Derived scenario creation failed','danger');return;}
    const c=await fetch('/api/scenarios');catalog=await c.json();
    scenario.replaceChildren(...catalog.scenarios.map(x=>{const o=document.createElement('option');o.value=x;o.textContent=x;return o;}));
    scenario.value=d.scenario_name;
    await loadScenario();
    workbookMessage('Сохранён производный сценарий: '+d.scenario_name+'; parent hash='+d.parent_config_hash+'; child hash='+d.child_config_hash,'ok');
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

    @app.post("/api/workbook/apply-derived")
    def apply_workbook_route(request: ApplyWorkbookRequest) -> dict[str, object]:
        try:
            return apply_workbook_as_derived(scenario_root, request)
        except (ValueError, TypeError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
