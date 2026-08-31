from __future__ import annotations

from datetime import UTC
from pathlib import Path

import yaml
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from constellation_control.adapters.norad import NoradFormat, NoradImportPreview, preview_norad_import
from constellation_control.adapters.orekit.mean_conversion import OrekitTleMeanConversionClient
from constellation_control.application.run import load_scenario
from constellation_control.domain.digital_twin import DigitalTwinConfig, ScenarioLineage
from constellation_control.domain.models import ScenarioConfig


class NoradPreviewRequest(BaseModel):
    filename: str
    content_text: str


class NoradAuthorityRequest(NoradPreviewRequest):
    source_scenario_name: str
    satellite_id: str
    norad_satellite_number: int


class NoradCreateRequest(NoradAuthorityRequest):
    target_scenario_name: str
    new_scenario_id: str


def _tle_pair(content: str, satellite_number: int) -> tuple[str, str]:
    lines = [line.rstrip("\r") for line in content.splitlines() if line.strip()]
    index = 0
    while index < len(lines):
        if not lines[index].startswith("1 "):
            index += 1
        if index + 1 >= len(lines):
            break
        line1 = lines[index]
        line2 = lines[index + 1]
        if line1.startswith("1 ") and line2.startswith("2 "):
            try:
                candidate = int(line1[2:7])
            except ValueError:
                candidate = -1
            if candidate == satellite_number:
                return line1, line2
            index += 2
        else:
            index += 1
    raise ValueError(f"NORAD satellite {satellite_number} has no raw TLE pair in the uploaded source")


def _selected_tle(preview: NoradImportPreview, satellite_number: int):
    record = next((item for item in preview.records if item.satellite_number == satellite_number), None)
    if record is None:
        raise ValueError(f"unknown NORAD satellite number: {satellite_number}")
    if record.source_format != NoradFormat.TLE:
        raise ValueError("OMM remains non-promotable; authoritative derived scenarios currently require raw TLE")
    return record


def _source(root: Path, request: NoradAuthorityRequest):
    source = load_scenario(root / request.source_scenario_name)
    satellite = next((item for item in source.constellation.satellites if item.satellite_id == request.satellite_id), None)
    if satellite is None:
        raise ValueError(f"unknown satellite_id: {request.satellite_id}")
    if not source.orekit_sidecar_url:
        raise ValueError("selected scenario has no orekit_sidecar_url; authoritative TLE conversion is unavailable")
    return source, satellite


def _authority(root: Path, request: NoradAuthorityRequest):
    preview = preview_norad_import(request.filename, request.content_text)
    record = _selected_tle(preview, request.norad_satellite_number)
    source, satellite = _source(root, request)
    source_epoch = source.epoch.astimezone(UTC)
    tle_epoch = record.epoch_utc.astimezone(UTC)
    if abs((tle_epoch - source_epoch).total_seconds()) > 1.0e-6:
        raise ValueError(
            "TLE epoch does not match parent scenario epoch; promotion is blocked until the Orekit TLE authority "
            "supports propagation to the explicit scenario epoch"
        )
    line1, line2 = _tle_pair(request.content_text, request.norad_satellite_number)
    result = OrekitTleMeanConversionClient(source.orekit_sidecar_url).convert(
        line1=line1,
        line2=line2,
        frame=source.frame,
        spacecraft=satellite.spacecraft,
        force_model=source.force_model,
    )
    if result.backend_metadata.get("norad_satellite_number") != str(request.norad_satellite_number):
        raise RuntimeError("Orekit TLE authority returned a different NORAD satellite number")
    return preview, record, source, satellite, result


def preview_norad_authority(root: Path, request: NoradAuthorityRequest) -> dict[str, object]:
    preview, record, source, satellite, result = _authority(root, request)
    return {
        "valid": True,
        "source_scenario_id": source.scenario_id,
        "source_config_hash": source.config_hash(),
        "source_filename": preview.source_filename,
        "source_sha256": preview.source_sha256,
        "satellite_id": satellite.satellite_id,
        "norad_satellite_number": record.satellite_number,
        "tle_epoch_utc": record.epoch_utc.isoformat(),
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


def create_norad_derived_scenario(root: Path, request: NoradCreateRequest) -> dict[str, object]:
    preview, record, source, satellite, result = _authority(root, request)
    if request.new_scenario_id == source.scenario_id:
        raise ValueError("new_scenario_id must differ from parent scenario_id")
    target = _target(root, request.target_scenario_name)
    satellites = tuple(
        item.model_copy(update={"mean_orbit": result.mean_orbit}) if item.satellite_id == request.satellite_id else item
        for item in source.constellation.satellites
    )
    constellation = source.constellation.model_copy(update={"satellites": satellites})
    prior_twin = source.digital_twin or DigitalTwinConfig()
    digital_twin = prior_twin.model_copy(
        update={
            "lineage": ScenarioLineage(
                parent_scenario_id=source.scenario_id,
                parent_config_hash=source.config_hash(),
                transformation="norad_tle_import",
                random_seed=None,
                source_type="norad_tle",
                source_name=preview.source_filename,
                source_sha256=preview.source_sha256,
                source_record_id=str(record.satellite_number),
                authority=result.backend_metadata.get("source_authority", "NORAD-TLE-SGP4"),
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
        "scenario_name": target.name,
        "scenario_id": child.scenario_id,
        "satellite_id": satellite.satellite_id,
        "norad_satellite_number": record.satellite_number,
        "parent_scenario_id": source.scenario_id,
        "parent_config_hash": source.config_hash(),
        "child_config_hash": child.config_hash(),
        "source_filename": preview.source_filename,
        "source_sha256": preview.source_sha256,
        "backend_metadata": result.backend_metadata,
    }


NORAD_CARD = r"""
<div class="card" id="noradCard">
  <h3>NORAD TLE / OMM</h3>
  <p class="hint">TLE сначала валидируется как NORAD/SGP4 mean-element input, затем только через authoritative Orekit chain TLE→SGP4/TEME→osculating PV→DSST mean может заменить орбиту выбранного КА. OMM остаётся fail-closed. В этом срезе эпоха TLE должна точно совпадать с эпохой parent scenario.</p>
  <input id="noradFile" type="file" accept=".tle,.txt,.json">
  <button onclick="previewNorad()">Проверить NORAD файл / Preview NORAD file</button>
  <div class="grid">
    <label>Запись NORAD / Record <select id="noradRecord"></select></label>
    <label>КА сценария / Scenario satellite <select id="noradSat"></select></label>
  </div>
  <button onclick="previewNoradAuthority()">Проверить через Orekit / Preview via Orekit</button>
  <pre id="noradPreview"></pre>
  <label>Новый scenario_id <input id="noradScenarioId" type="text" placeholder="derived-norad-01"></label>
  <label>Новый YAML <input id="noradScenarioFile" type="text" placeholder="derived-norad-01.yaml"></label>
  <button onclick="createNoradScenario()">Создать производный сценарий / Create derived scenario</button>
  <div id="noradStatus" class="status"></div>
</div>
"""

NORAD_SCRIPT = r"""
let noradLast=null;
function syncNoradSatellites(){if(!current)return;const sats=((current.normalized||current).constellation||{}).satellites||[];noradSat.replaceChildren(...sats.map(s=>{const o=document.createElement('option');o.value=s.satellite_id;o.textContent=s.satellite_id;return o;}));}
async function previewNorad(){
 const input=document.getElementById('noradFile');const file=input.files&&input.files[0];
 if(!file){noradStatus.textContent='Выберите .tle/.txt или OMM .json';noradStatus.className='status danger';return;}
 const text=await file.text();noradStatus.textContent='Validation…';
 const r=await fetch('/api/norad/preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({filename:file.name,content_text:text})});const d=await r.json();
 if(!r.ok){noradStatus.textContent=d.detail||'NORAD preview failed';noradStatus.className='status danger';return;}
 noradLast={filename:file.name,content_text:text,preview:d};
 noradRecord.replaceChildren(...d.records.map(x=>{const o=document.createElement('option');o.value=String(x.satellite_number);o.textContent=String(x.satellite_number)+(x.object_name?' — '+x.object_name:'')+' ['+x.source_format+']';return o;}));
 noradPreview.textContent=JSON.stringify(d,null,2);noradStatus.textContent='VALID: records='+d.records.length+'; raw promotion='+d.runnable_promotion_allowed;noradStatus.className='status ok';
}
function noradAuthorityPayload(){if(!noradLast)throw new Error('preview NORAD file first');if(!noradRecord.value)throw new Error('NORAD record is required');if(!noradSat.value)throw new Error('scenario satellite is required');return {filename:noradLast.filename,content_text:noradLast.content_text,source_scenario_name:scenario.value,satellite_id:noradSat.value,norad_satellite_number:Number(noradRecord.value)};}
async function previewNoradAuthority(){let p;try{p=noradAuthorityPayload();}catch(e){noradStatus.textContent=String(e.message||e);noradStatus.className='status danger';return;}noradStatus.textContent='Orekit TLE authority…';const r=await fetch('/api/norad/authority',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)});const d=await r.json();if(!r.ok){noradStatus.textContent=d.detail||'TLE authority failed';noradStatus.className='status danger';return;}noradPreview.textContent=JSON.stringify(d,null,2);noradStatus.textContent='AUTHORITY VALID: '+d.backend_metadata.source_authority+'; '+d.backend_metadata.sgp4_frame;noradStatus.className='status ok';}
async function createNoradScenario(){let base;try{base=noradAuthorityPayload();}catch(e){noradStatus.textContent=String(e.message||e);noradStatus.className='status danger';return;}const p={...base,new_scenario_id:noradScenarioId.value.trim(),target_scenario_name:noradScenarioFile.value.trim()};if(!p.new_scenario_id||!p.target_scenario_name){noradStatus.textContent='Укажите новый scenario_id и YAML';noradStatus.className='status danger';return;}const r=await fetch('/api/norad/create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)});const d=await r.json();if(!r.ok){noradStatus.textContent=d.detail||'Create failed';noradStatus.className='status danger';return;}const c=await fetch('/api/scenarios');catalog=await c.json();scenario.replaceChildren(...catalog.scenarios.map(x=>{const o=document.createElement('option');o.value=x;o.textContent=x;return o;}));scenario.value=d.scenario_name;await loadScenario();noradStatus.textContent='Создан: '+d.scenario_name;noradStatus.className='status ok';}
"""


def install_norad_routes(app: FastAPI, scenario_root: Path) -> None:
    @app.post("/api/norad/preview")
    def preview(request: NoradPreviewRequest) -> dict[str, object]:
        try:
            return preview_norad_import(request.filename, request.content_text).model_dump(mode="json")
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/norad/authority")
    def authority(request: NoradAuthorityRequest) -> dict[str, object]:
        try:
            return preview_norad_authority(scenario_root, request)
        except (ValueError, TypeError, RuntimeError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/norad/create")
    def create(request: NoradCreateRequest) -> dict[str, object]:
        try:
            return create_norad_derived_scenario(scenario_root, request)
        except (ValueError, TypeError, RuntimeError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
