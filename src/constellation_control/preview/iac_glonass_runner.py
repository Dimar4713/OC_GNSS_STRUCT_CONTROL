from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from constellation_control.adapters.iac_glonass_almanac import normalize_iac_glonass_almanac
from constellation_control.adapters.iac_glonass_authority_bridge import (
    IacGlonassAuthoritySupplement,
    iac_glonass_to_authority_record,
)
from constellation_control.adapters.iac_gnss_tables import IacDataset, fetch_iac_table, parse_iac_text
from constellation_control.adapters.orekit.mean_conversion import OrekitGlonassAlmanacMeanConversionClient
from constellation_control.application.run import load_scenario
from constellation_control.domain.digital_twin import DigitalTwinConfig, ScenarioLineage
from constellation_control.domain.models import ScenarioConfig


class IacGlonassRunnerAuthorityRequest(BaseModel):
    source_mode: Literal["online", "offline"]
    filename: str | None = None
    content_text: str | None = None
    source_scenario_name: str
    satellite_id: str
    slot: int
    health: int
    glo_to_utc_s: float
    gps_to_glo_s: float
    glo_time_offset_s: float


class IacGlonassRunnerCreateRequest(IacGlonassRunnerAuthorityRequest):
    target_scenario_name: str
    new_scenario_id: str


def _table(request: IacGlonassRunnerAuthorityRequest):
    if request.source_mode == "online":
        return fetch_iac_table(IacDataset.GLONASS_ALMANAC)
    if not request.filename or Path(request.filename).name != request.filename:
        raise ValueError("offline IAC GLONASS source requires a plain source filename")
    if request.content_text is None or not request.content_text.strip():
        raise ValueError("offline IAC GLONASS source is empty")
    return parse_iac_text(IacDataset.GLONASS_ALMANAC, request.content_text)


def _authority(root: Path, request: IacGlonassRunnerAuthorityRequest):
    table = _table(request)
    almanac = normalize_iac_glonass_almanac(table)
    record = next((item for item in almanac.records if item.slot == request.slot), None)
    if record is None:
        raise ValueError(f"unknown IAC GLONASS slot: {request.slot}")

    supplement = IacGlonassAuthoritySupplement(
        health=request.health,
        glo_to_utc_s=request.glo_to_utc_s,
        gps_to_glo_s=request.gps_to_glo_s,
        glo_time_offset_s=request.glo_time_offset_s,
    )
    authority_record = iac_glonass_to_authority_record(record, supplement)

    source = load_scenario(root / request.source_scenario_name)
    satellite = next(
        (item for item in source.constellation.satellites if item.satellite_id == request.satellite_id),
        None,
    )
    if satellite is None:
        raise ValueError(f"unknown satellite_id: {request.satellite_id}")
    if not source.orekit_sidecar_url:
        raise ValueError("selected scenario has no orekit_sidecar_url; IAC GLONASS authority is unavailable")

    source_name = table.source_url or request.filename or "iac-glonass-offline"
    result = OrekitGlonassAlmanacMeanConversionClient(source.orekit_sidecar_url).convert(
        source_name=source_name,
        slot=authority_record.slot,
        frequency_channel=authority_record.frequency_channel,
        health=authority_record.health,
        reference_date=authority_record.reference_date,
        reference_time_s=authority_record.reference_time_s,
        lambda_rad=authority_record.lambda_rad,
        delta_i_rad=authority_record.delta_i_rad,
        argument_of_perigee_rad=authority_record.argument_of_perigee_rad,
        eccentricity=authority_record.eccentricity,
        delta_t_s=authority_record.delta_t_s,
        delta_t_dot=authority_record.delta_t_dot,
        glo_to_utc_s=authority_record.glo_to_utc_s,
        gps_to_glo_s=authority_record.gps_to_glo_s,
        glo_time_offset_s=authority_record.glo_time_offset_s,
        frame=source.frame,
        target_epoch=source.epoch,
        target_time_scale=source.time_scale,
        spacecraft=satellite.spacecraft,
        force_model=source.force_model,
    )
    if result.backend_metadata.get("glonass_slot") != str(request.slot):
        raise RuntimeError("Orekit IAC GLONASS authority returned a different slot")
    return table, record, source, satellite, result


def preview_iac_glonass_runner_authority(
    root: Path,
    request: IacGlonassRunnerAuthorityRequest,
) -> dict[str, object]:
    table, record, source, satellite, result = _authority(root, request)
    return {
        "valid": True,
        "source_mode": request.source_mode,
        "source_url": table.source_url,
        "source_filename": request.filename if request.source_mode == "offline" else None,
        "source_sha256": table.source_sha256,
        "source_scenario_id": source.scenario_id,
        "source_config_hash": source.config_hash(),
        "satellite_id": satellite.satellite_id,
        "slot": record.slot,
        "frequency_channel": record.frequency_channel,
        "target_scenario_epoch": source.epoch.isoformat(),
        "target_time_scale": source.time_scale.value,
        "mean_orbit": result.mean_orbit.model_dump(mode="json"),
        "backend_metadata": result.backend_metadata,
    }


def _target(root: Path, name: str) -> Path:
    if not name or Path(name).name != name or not name.lower().endswith((".yaml", ".yml")):
        raise ValueError("target_scenario_name must be a new YAML file name without path components")
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = (root / name).resolve()
    if target.parent != root:
        raise ValueError("invalid target scenario path")
    if target.exists():
        raise ValueError("target scenario already exists; overwrite is forbidden")
    return target


def create_iac_glonass_runner_scenario(
    root: Path,
    request: IacGlonassRunnerCreateRequest,
) -> dict[str, object]:
    table, record, source, satellite, result = _authority(root, request)
    if request.new_scenario_id == source.scenario_id:
        raise ValueError("new_scenario_id must differ from parent scenario_id")
    target = _target(root, request.target_scenario_name)

    satellites = tuple(
        item.model_copy(update={"mean_orbit": result.mean_orbit})
        if item.satellite_id == request.satellite_id
        else item
        for item in source.constellation.satellites
    )
    constellation = source.constellation.model_copy(update={"satellites": satellites})
    prior_twin = source.digital_twin or DigitalTwinConfig()
    source_name = table.source_url or request.filename or "iac-glonass-offline"
    digital_twin = prior_twin.model_copy(
        update={
            "lineage": ScenarioLineage(
                parent_scenario_id=source.scenario_id,
                parent_config_hash=source.config_hash(),
                transformation="glonass_almanac_import",
                random_seed=None,
                source_type="glonass_authority_v1",
                source_name=source_name,
                source_sha256=table.source_sha256,
                source_record_id=str(record.slot),
                authority=(
                    result.backend_metadata.get("source_authority", "GLONASS-ALMANAC-OREKIT-ANALYTICAL")
                    + "; IAC normalized bridge with explicit operator supplement"
                ),
            )
        }
    )
    child = ScenarioConfig.model_validate(
        source.model_dump(mode="json")
        | {
            "scenario_id": request.new_scenario_id,
            "constellation": constellation.model_dump(mode="json"),
            "digital_twin": digital_twin.model_dump(mode="json"),
        }
    )
    target.write_text(
        yaml.safe_dump(child.model_dump(mode="json"), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return {
        "saved": True,
        "runnable": True,
        "scenario_name": target.name,
        "scenario_id": child.scenario_id,
        "satellite_id": satellite.satellite_id,
        "slot": record.slot,
        "parent_scenario_id": source.scenario_id,
        "parent_config_hash": source.config_hash(),
        "child_config_hash": child.config_hash(),
        "source_mode": request.source_mode,
        "source_url": table.source_url,
        "source_filename": request.filename if request.source_mode == "offline" else None,
        "source_sha256": table.source_sha256,
        "backend_metadata": result.backend_metadata,
    }


IAC_GLONASS_RUNNER_CARD = r"""
<div class="card" id="iacGlonassRunnerCard">
  <h3>ИАЦ GLONASS → runnable scenario</h3>
  <p class="hint">Сквозной тракт: glonass-iac.ru / offline canonical table → проверенная нормализация → explicit authority supplement → Orekit GLONASS analytical propagation → DSST mean → новый ScenarioConfig. Недостающие в таблице ИАЦ time/health поля никогда не подставляются скрыто.</p>
  <div class="grid">
    <label>Источник / Source
      <select id="iacGloRunnerMode"><option value="online">Online IAC</option><option value="offline">Offline file</option></select>
    </label>
    <label>Offline TXT/TSV <input id="iacGloRunnerFile" type="file" accept=".txt,.tsv,.csv"></label>
  </div>
  <div class="grid"><label>Slot <input id="iacGloRunnerSlot" type="number" min="1" max="63" value="1"></label><label>КА сценария / Scenario satellite <select id="iacGloRunnerSat"></select></label></div>
  <div class="grid"><label>Health <input id="iacGloHealth" type="number" min="0" value="0"></label><label>GLO→UTC, s <input id="iacGloUtc" type="number" step="any"></label></div>
  <div class="grid"><label>GPS→GLO, s <input id="iacGpsGlo" type="number" step="any"></label><label>GLO time offset, s <input id="iacGloOffset" type="number" step="any"></label></div>
  <button onclick="previewIacGlonassRunnerAuthority()">Проверить authority / Preview authority</button>
  <pre id="iacGloRunnerPreview"></pre>
  <label>Новый scenario_id <input id="iacGloRunnerScenarioId" type="text" placeholder="iac-glonass-derived-01"></label>
  <label>Новый YAML <input id="iacGloRunnerScenarioFile" type="text" placeholder="iac-glonass-derived-01.yaml"></label>
  <button onclick="createIacGlonassRunnerScenario()">Собрать runnable scenario / Build runnable scenario</button>
  <div id="iacGloRunnerStatus" class="status"></div>
</div>
"""

IAC_GLONASS_RUNNER_SCRIPT = r"""
function syncIacGlonassRunnerSatellites(){if(!current)return;const sats=((current.normalized||current).constellation||{}).satellites||[];iacGloRunnerSat.replaceChildren(...sats.map(s=>{const o=document.createElement('option');o.value=s.satellite_id;o.textContent=s.satellite_id;return o;}));}
function iacGloStatus(t,k=''){iacGloRunnerStatus.textContent=t;iacGloRunnerStatus.className='status '+k;}
async function iacGloRunnerPayload(){
 const mode=iacGloRunnerMode.value;let filename=null,content_text=null;
 if(mode==='offline'){const f=iacGloRunnerFile.files&&iacGloRunnerFile.files[0];if(!f)throw new Error('Выберите offline IAC GLONASS файл');filename=f.name;content_text=await f.text();}
 const numbers=[iacGloUtc.value,iacGpsGlo.value,iacGloOffset.value];if(numbers.some(x=>x.trim()===''))throw new Error('Укажите все три time-correction authority значения');
 return {source_mode:mode,filename,content_text,source_scenario_name:scenario.value,satellite_id:iacGloRunnerSat.value,slot:Number(iacGloRunnerSlot.value),health:Number(iacGloHealth.value),glo_to_utc_s:Number(iacGloUtc.value),gps_to_glo_s:Number(iacGpsGlo.value),glo_time_offset_s:Number(iacGloOffset.value)};
}
async function previewIacGlonassRunnerAuthority(){let p;try{p=await iacGloRunnerPayload();}catch(e){iacGloStatus(String(e.message||e),'danger');return;}iacGloStatus('IAC → Orekit authority…');const r=await fetch('/api/iac-glonass-runner/authority',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)});const d=await r.json();if(!r.ok){iacGloStatus(d.detail||'IAC GLONASS authority failed','danger');return;}iacGloRunnerPreview.textContent=JSON.stringify(d,null,2);iacGloStatus('AUTHORITY VALID: slot='+d.slot+'; source sha256='+d.source_sha256,'ok');}
async function createIacGlonassRunnerScenario(){let p;try{p=await iacGloRunnerPayload();}catch(e){iacGloStatus(String(e.message||e),'danger');return;}p={...p,new_scenario_id:iacGloRunnerScenarioId.value.trim(),target_scenario_name:iacGloRunnerScenarioFile.value.trim()};if(!p.new_scenario_id||!p.target_scenario_name){iacGloStatus('Укажите новый scenario_id и YAML','danger');return;}iacGloStatus('Сборка runnable scenario…');const r=await fetch('/api/iac-glonass-runner/create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)});const d=await r.json();if(!r.ok){iacGloStatus(d.detail||'Build failed','danger');return;}const c=await fetch('/api/scenarios');catalog=await c.json();scenario.replaceChildren(...catalog.scenarios.map(x=>{const o=document.createElement('option');o.value=x;o.textContent=x;return o;}));scenario.value=d.scenario_name;await loadScenario();iacGloStatus('RUNNABLE: '+d.scenario_name+'; '+d.child_config_hash,'ok');}
"""


def install_iac_glonass_runner_routes(app: FastAPI, scenario_root: Path = Path("scenarios")) -> None:
    @app.post("/api/iac-glonass-runner/authority")
    def authority(request: IacGlonassRunnerAuthorityRequest) -> dict[str, object]:
        try:
            return preview_iac_glonass_runner_authority(scenario_root, request)
        except (ValueError, TypeError, RuntimeError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/iac-glonass-runner/create")
    def create(request: IacGlonassRunnerCreateRequest) -> dict[str, object]:
        try:
            return create_iac_glonass_runner_scenario(scenario_root, request)
        except (ValueError, TypeError, RuntimeError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
