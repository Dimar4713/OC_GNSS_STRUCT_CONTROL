from __future__ import annotations

from pathlib import Path

import yaml
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from constellation_control.adapters.gnss_almanac import GnssAlmanacFormat, preview_gnss_almanac
from constellation_control.adapters.orekit.mean_conversion import OrekitGpsAlmanacMeanConversionClient
from constellation_control.application.run import load_scenario
from constellation_control.domain.digital_twin import DigitalTwinConfig, ScenarioLineage
from constellation_control.domain.models import ScenarioConfig


class GnssAlmanacPreviewRequest(BaseModel):
    filename: str
    content_text: str
    source_format: GnssAlmanacFormat


class GpsAlmanacAuthorityRequest(GnssAlmanacPreviewRequest):
    source_scenario_name: str
    satellite_id: str
    prn: int


class GpsAlmanacCreateRequest(GpsAlmanacAuthorityRequest):
    target_scenario_name: str
    new_scenario_id: str


def _gps_record(preview, prn: int):
    if preview.source_format not in (GnssAlmanacFormat.GPS_YUMA, GnssAlmanacFormat.GPS_SEM):
        raise ValueError("GLONASS remains preview-only and cannot use GPS almanac authority")
    record = next((item for item in preview.records if getattr(item, "prn", None) == prn), None)
    if record is None:
        raise ValueError(f"unknown GPS almanac PRN: {prn}")
    return record


def _source(root: Path, request: GpsAlmanacAuthorityRequest):
    source = load_scenario(root / request.source_scenario_name)
    satellite = next((item for item in source.constellation.satellites if item.satellite_id == request.satellite_id), None)
    if satellite is None:
        raise ValueError(f"unknown satellite_id: {request.satellite_id}")
    if not source.orekit_sidecar_url:
        raise ValueError("selected scenario has no orekit_sidecar_url; GPS almanac authority is unavailable")
    return source, satellite


def _authority(root: Path, request: GpsAlmanacAuthorityRequest):
    preview = preview_gnss_almanac(request.filename, request.content_text, request.source_format)
    record = _gps_record(preview, request.prn)
    source, satellite = _source(root, request)
    result = OrekitGpsAlmanacMeanConversionClient(source.orekit_sidecar_url).convert(
        source_format=request.source_format.value,
        source_name=preview.source_filename,
        source_text=request.content_text,
        prn=request.prn,
        frame=source.frame,
        target_epoch=source.epoch,
        target_time_scale=source.time_scale,
        spacecraft=satellite.spacecraft,
        force_model=source.force_model,
    )
    if result.backend_metadata.get("gps_prn") != str(request.prn):
        raise RuntimeError("Orekit GPS almanac authority returned a different PRN")
    return preview, record, source, satellite, result


def preview_gps_almanac_authority(root: Path, request: GpsAlmanacAuthorityRequest) -> dict[str, object]:
    preview, _record, source, satellite, result = _authority(root, request)
    return {
        "valid": True,
        "source_scenario_id": source.scenario_id,
        "source_config_hash": source.config_hash(),
        "source_format": preview.source_format.value,
        "source_filename": preview.source_filename,
        "source_sha256": preview.source_sha256,
        "satellite_id": satellite.satellite_id,
        "prn": request.prn,
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


def create_gps_almanac_derived_scenario(root: Path, request: GpsAlmanacCreateRequest) -> dict[str, object]:
    preview, _record, source, satellite, result = _authority(root, request)
    if request.new_scenario_id == source.scenario_id:
        raise ValueError("new_scenario_id must differ from parent scenario_id")
    target = _target(root, request.target_scenario_name)
    satellites = tuple(
        item.model_copy(update={"mean_orbit": result.mean_orbit}) if item.satellite_id == request.satellite_id else item
        for item in source.constellation.satellites
    )
    constellation = source.constellation.model_copy(update={"satellites": satellites})
    prior_twin = source.digital_twin or DigitalTwinConfig()
    source_type = "gps_yuma" if preview.source_format == GnssAlmanacFormat.GPS_YUMA else "gps_sem"
    digital_twin = prior_twin.model_copy(
        update={
            "lineage": ScenarioLineage(
                parent_scenario_id=source.scenario_id,
                parent_config_hash=source.config_hash(),
                transformation="gps_almanac_import",
                random_seed=None,
                source_type=source_type,
                source_name=preview.source_filename,
                source_sha256=preview.source_sha256,
                source_record_id=str(request.prn),
                authority=result.backend_metadata.get("source_authority", "GPS-ALMANAC-OREKIT-GNSS"),
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
    target.write_text(yaml.safe_dump(child.model_dump(mode="json"), sort_keys=False, allow_unicode=True), encoding="utf-8")
    return {
        "saved": True,
        "scenario_name": target.name,
        "scenario_id": child.scenario_id,
        "satellite_id": satellite.satellite_id,
        "prn": request.prn,
        "parent_scenario_id": source.scenario_id,
        "parent_config_hash": source.config_hash(),
        "child_config_hash": child.config_hash(),
        "source_format": preview.source_format.value,
        "source_filename": preview.source_filename,
        "source_sha256": preview.source_sha256,
        "backend_metadata": result.backend_metadata,
    }


GNSS_ALMANAC_CARD = r"""
<div class="card" id="gnssAlmanacCard">
  <h3>GNSS Almanac intake</h3>
  <p class="hint">GPS YUMA/SEM: raw source остаётся almanac input; runnable child создаётся только через Orekit parser → GPS GNSS propagator@parent epoch → osculating PV → DSST mean. GLONASS labelled text остаётся preview-only.</p>
  <div class="grid">
    <label>Формат / Format
      <select id="gnssAlmanacFormat">
        <option value="gps-yuma">GPS YUMA</option>
        <option value="gps-sem">GPS SEM</option>
        <option value="glonass-text">GLONASS labelled text</option>
      </select>
    </label>
    <label>Файл / File <input id="gnssAlmanacFile" type="file" accept=".alm,.al3,.txt"></label>
  </div>
  <button onclick="previewGnssAlmanac()">Проверить альманах / Preview almanac</button>
  <div class="grid"><label>PRN <select id="gnssAlmanacPrn"></select></label><label>КА сценария / Scenario satellite <select id="gnssAlmanacSat"></select></label></div>
  <button onclick="previewGpsAlmanacAuthority()">Проверить через Orekit / Preview via Orekit</button>
  <pre id="gnssAlmanacPreview"></pre>
  <label>Новый scenario_id <input id="gnssAlmanacScenarioId" type="text" placeholder="derived-gps-almanac-01"></label>
  <label>Новый YAML <input id="gnssAlmanacScenarioFile" type="text" placeholder="derived-gps-almanac-01.yaml"></label>
  <button onclick="createGpsAlmanacScenario()">Создать производный сценарий / Create derived scenario</button>
  <div id="gnssAlmanacStatus" class="status"></div>
</div>
"""

GNSS_ALMANAC_SCRIPT = r"""
let gnssAlmanacLast=null;
function syncGnssAlmanacSatellites(){if(!current)return;const sats=((current.normalized||current).constellation||{}).satellites||[];gnssAlmanacSat.replaceChildren(...sats.map(s=>{const o=document.createElement('option');o.value=s.satellite_id;o.textContent=s.satellite_id;return o;}));}
const gnssAlmanacPriorLoadScenario=loadScenario;
loadScenario=async function(){await gnssAlmanacPriorLoadScenario();syncGnssAlmanacSatellites();};
async function previewGnssAlmanac(){
 const file=gnssAlmanacFile.files&&gnssAlmanacFile.files[0];
 if(!file){gnssAlmanacStatus.textContent='Выберите файл альманаха';gnssAlmanacStatus.className='status danger';return;}
 const text=await file.text();gnssAlmanacStatus.textContent='Validation…';
 const format=gnssAlmanacFormat.value;
 const r=await fetch('/api/gnss-almanac/preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({filename:file.name,content_text:text,source_format:format})});
 const d=await r.json();
 if(!r.ok){gnssAlmanacStatus.textContent=d.detail||'Almanac preview failed';gnssAlmanacStatus.className='status danger';return;}
 gnssAlmanacLast={filename:file.name,content_text:text,source_format:format,preview:d};
 const gps=format==='gps-yuma'||format==='gps-sem';
 gnssAlmanacPrn.replaceChildren(...(gps?d.records:[]).map(x=>{const o=document.createElement('option');o.value=String(x.prn);o.textContent='PRN '+x.prn;return o;}));
 gnssAlmanacPreview.textContent=JSON.stringify(d,null,2);
 gnssAlmanacStatus.textContent='VALID: '+d.source_format+'; records='+d.records.length+'; raw runnable='+d.runnable_promotion_allowed+(gps?'':'; GLONASS authority blocked');
 gnssAlmanacStatus.className='status ok';
}
function gpsAlmanacAuthorityPayload(){if(!gnssAlmanacLast)throw new Error('preview almanac first');if(gnssAlmanacLast.source_format==='glonass-text')throw new Error('GLONASS remains preview-only');if(!gnssAlmanacPrn.value)throw new Error('GPS PRN is required');if(!gnssAlmanacSat.value)throw new Error('scenario satellite is required');return {filename:gnssAlmanacLast.filename,content_text:gnssAlmanacLast.content_text,source_format:gnssAlmanacLast.source_format,source_scenario_name:scenario.value,satellite_id:gnssAlmanacSat.value,prn:Number(gnssAlmanacPrn.value)};}
async function previewGpsAlmanacAuthority(){let p;try{p=gpsAlmanacAuthorityPayload();}catch(e){gnssAlmanacStatus.textContent=String(e.message||e);gnssAlmanacStatus.className='status danger';return;}gnssAlmanacStatus.textContent='Orekit GPS almanac authority…';const r=await fetch('/api/gnss-almanac/authority',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)});const d=await r.json();if(!r.ok){gnssAlmanacStatus.textContent=d.detail||'GPS almanac authority failed';gnssAlmanacStatus.className='status danger';return;}gnssAlmanacPreview.textContent=JSON.stringify(d,null,2);gnssAlmanacStatus.textContent='AUTHORITY VALID: '+d.backend_metadata.source_authority+'; target='+d.target_scenario_epoch;gnssAlmanacStatus.className='status ok';}
async function createGpsAlmanacScenario(){let base;try{base=gpsAlmanacAuthorityPayload();}catch(e){gnssAlmanacStatus.textContent=String(e.message||e);gnssAlmanacStatus.className='status danger';return;}const p={...base,new_scenario_id:gnssAlmanacScenarioId.value.trim(),target_scenario_name:gnssAlmanacScenarioFile.value.trim()};if(!p.new_scenario_id||!p.target_scenario_name){gnssAlmanacStatus.textContent='Укажите новый scenario_id и YAML';gnssAlmanacStatus.className='status danger';return;}const r=await fetch('/api/gnss-almanac/create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)});const d=await r.json();if(!r.ok){gnssAlmanacStatus.textContent=d.detail||'Create failed';gnssAlmanacStatus.className='status danger';return;}const c=await fetch('/api/scenarios');catalog=await c.json();scenario.replaceChildren(...catalog.scenarios.map(x=>{const o=document.createElement('option');o.value=x;o.textContent=x;return o;}));scenario.value=d.scenario_name;await loadScenario();gnssAlmanacStatus.textContent='Создан: '+d.scenario_name;gnssAlmanacStatus.className='status ok';}
"""


def install_gnss_almanac_routes(app: FastAPI, scenario_root: Path = Path("scenarios")) -> None:
    @app.post("/api/gnss-almanac/preview")
    def preview(request: GnssAlmanacPreviewRequest) -> dict[str, object]:
        try:
            return preview_gnss_almanac(
                request.filename,
                request.content_text,
                request.source_format,
            ).model_dump(mode="json")
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/gnss-almanac/authority")
    def authority(request: GpsAlmanacAuthorityRequest) -> dict[str, object]:
        try:
            return preview_gps_almanac_authority(scenario_root, request)
        except (ValueError, TypeError, RuntimeError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/gnss-almanac/create")
    def create(request: GpsAlmanacCreateRequest) -> dict[str, object]:
        try:
            return create_gps_almanac_derived_scenario(scenario_root, request)
        except (ValueError, TypeError, RuntimeError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
