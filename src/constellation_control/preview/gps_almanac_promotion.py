from __future__ import annotations

from pathlib import Path

import yaml
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from constellation_control.adapters.gnss_almanac import (
    GnssAlmanacFormat,
    GpsSemRecord,
    GpsYumaRecord,
    preview_gnss_almanac,
)
from constellation_control.adapters.orekit.mean_conversion import OrekitGpsAlmanacMeanConversionClient
from constellation_control.application.run import load_scenario
from constellation_control.domain.digital_twin import DigitalTwinConfig, ScenarioLineage
from constellation_control.domain.models import ScenarioConfig


class GpsAlmanacAuthorityRequest(BaseModel):
    filename: str
    content_text: str
    source_format: GnssAlmanacFormat
    source_scenario_name: str
    satellite_id: str
    prn: int


class GpsAlmanacCreateRequest(GpsAlmanacAuthorityRequest):
    target_scenario_name: str
    new_scenario_id: str


def _selected_record(preview, prn: int) -> GpsYumaRecord | GpsSemRecord:
    if preview.source_format not in (GnssAlmanacFormat.GPS_YUMA, GnssAlmanacFormat.GPS_SEM):
        raise ValueError("GLONASS remains preview-only and cannot use GPS almanac authority")
    record = next((item for item in preview.records if getattr(item, "prn", None) == prn), None)
    if not isinstance(record, (GpsYumaRecord, GpsSemRecord)):
        raise ValueError(f"GPS PRN {prn} is not present in the uploaded almanac")
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
    if request.source_format not in (GnssAlmanacFormat.GPS_YUMA, GnssAlmanacFormat.GPS_SEM):
        raise ValueError("only GPS YUMA/SEM are promotable through this authority path")
    preview = preview_gnss_almanac(request.filename, request.content_text, request.source_format)
    record = _selected_record(preview, request.prn)
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
    preview, record, source, satellite, result = _authority(root, request)
    return {
        "valid": True,
        "source_scenario_id": source.scenario_id,
        "source_config_hash": source.config_hash(),
        "source_filename": preview.source_filename,
        "source_sha256": preview.source_sha256,
        "source_format": preview.source_format.value,
        "satellite_id": satellite.satellite_id,
        "prn": record.prn,
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
    preview, record, source, satellite, result = _authority(root, request)
    if request.new_scenario_id == source.scenario_id:
        raise ValueError("new_scenario_id must differ from parent scenario_id")
    target = _target(root, request.target_scenario_name)
    satellites = tuple(
        item.model_copy(update={"mean_orbit": result.mean_orbit}) if item.satellite_id == request.satellite_id else item
        for item in source.constellation.satellites
    )
    constellation = source.constellation.model_copy(update={"satellites": satellites})
    source_type = "gps_yuma" if preview.source_format == GnssAlmanacFormat.GPS_YUMA else "gps_sem"
    prior_twin = source.digital_twin or DigitalTwinConfig()
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
                source_record_id=str(record.prn),
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
        "prn": record.prn,
        "source_format": preview.source_format.value,
        "parent_scenario_id": source.scenario_id,
        "parent_config_hash": source.config_hash(),
        "child_config_hash": child.config_hash(),
        "source_filename": preview.source_filename,
        "source_sha256": preview.source_sha256,
        "backend_metadata": result.backend_metadata,
    }


GPS_ALMANAC_PROMOTION_CARD = r"""
<div class="card" id="gpsAlmanacPromotionCard">
  <h3>GPS Almanac → derived scenario</h3>
  <p class="hint">Только YUMA/SEM. Raw файл повторно парсится Orekit, GPS GNSS propagator вычисляет состояние на эпоху parent scenario, затем выполняется DSST mean conversion. GLONASS здесь запрещён.</p>
  <div class="grid">
    <label>Format <select id="gpsPromoFormat"><option value="gps-yuma">GPS YUMA</option><option value="gps-sem">GPS SEM</option></select></label>
    <label>File <input id="gpsPromoFile" type="file" accept=".alm,.al3,.txt"></label>
    <label>PRN <input id="gpsPromoPrn" type="number" min="1" step="1"></label>
    <label>Scenario satellite <select id="gpsPromoSat"></select></label>
  </div>
  <button onclick="previewGpsAlmanacAuthority()">Проверить через Orekit / Preview authority</button>
  <pre id="gpsPromoPreview"></pre>
  <div class="grid">
    <label>New scenario_id <input id="gpsPromoScenarioId" type="text" placeholder="derived-gps-almanac-01"></label>
    <label>New YAML <input id="gpsPromoScenarioFile" type="text" placeholder="derived-gps-almanac-01.yaml"></label>
  </div>
  <button onclick="createGpsAlmanacScenario()">Создать производный сценарий / Create derived scenario</button>
  <div id="gpsPromoStatus" class="status"></div>
</div>
"""

GPS_ALMANAC_PROMOTION_SCRIPT = r"""
function syncGpsPromoSatellites(){if(!current)return;const sats=((current.normalized||current).constellation||{}).satellites||[];gpsPromoSat.replaceChildren(...sats.map(s=>{const o=document.createElement('option');o.value=s.satellite_id;o.textContent=s.satellite_id;return o;}));}
async function gpsPromoPayload(){const file=gpsPromoFile.files&&gpsPromoFile.files[0];if(!file)throw new Error('Select YUMA/SEM file');const prn=Number(gpsPromoPrn.value);if(!Number.isInteger(prn)||prn<=0)throw new Error('PRN is required');if(!gpsPromoSat.value)throw new Error('Scenario satellite is required');return {filename:file.name,content_text:await file.text(),source_format:gpsPromoFormat.value,source_scenario_name:scenario.value,satellite_id:gpsPromoSat.value,prn};}
async function previewGpsAlmanacAuthority(){let p;try{p=await gpsPromoPayload();}catch(e){gpsPromoStatus.textContent=String(e.message||e);gpsPromoStatus.className='status danger';return;}gpsPromoStatus.textContent='Orekit GPS almanac authority…';const r=await fetch('/api/gps-almanac/authority',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)});const d=await r.json();if(!r.ok){gpsPromoStatus.textContent=d.detail||'Authority failed';gpsPromoStatus.className='status danger';return;}gpsPromoPreview.textContent=JSON.stringify(d,null,2);gpsPromoStatus.textContent='AUTHORITY VALID: '+d.backend_metadata.source_authority+'; PRN='+d.prn;gpsPromoStatus.className='status ok';}
async function createGpsAlmanacScenario(){let base;try{base=await gpsPromoPayload();}catch(e){gpsPromoStatus.textContent=String(e.message||e);gpsPromoStatus.className='status danger';return;}const p={...base,new_scenario_id:gpsPromoScenarioId.value.trim(),target_scenario_name:gpsPromoScenarioFile.value.trim()};if(!p.new_scenario_id||!p.target_scenario_name){gpsPromoStatus.textContent='Supply new scenario_id and YAML';gpsPromoStatus.className='status danger';return;}const r=await fetch('/api/gps-almanac/create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)});const d=await r.json();if(!r.ok){gpsPromoStatus.textContent=d.detail||'Create failed';gpsPromoStatus.className='status danger';return;}const c=await fetch('/api/scenarios');catalog=await c.json();scenario.replaceChildren(...catalog.scenarios.map(x=>{const o=document.createElement('option');o.value=x;o.textContent=x;return o;}));scenario.value=d.scenario_name;await loadScenario();gpsPromoStatus.textContent='Создан: '+d.scenario_name;gpsPromoStatus.className='status ok';}
"""


def install_gps_almanac_promotion_routes(app: FastAPI, scenario_root: Path) -> None:
    @app.post("/api/gps-almanac/authority")
    def authority(request: GpsAlmanacAuthorityRequest) -> dict[str, object]:
        try:
            return preview_gps_almanac_authority(scenario_root, request)
        except (ValueError, TypeError, RuntimeError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/gps-almanac/create")
    def create(request: GpsAlmanacCreateRequest) -> dict[str, object]:
        try:
            return create_gps_almanac_derived_scenario(scenario_root, request)
        except (ValueError, TypeError, RuntimeError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
