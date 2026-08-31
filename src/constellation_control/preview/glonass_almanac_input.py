from __future__ import annotations

from pathlib import Path

import yaml
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from constellation_control.adapters.glonass_almanac_authority import (
    GlonassAuthorityRecord,
    parse_glonass_authority_source,
)
from constellation_control.adapters.orekit.mean_conversion import OrekitGlonassAlmanacMeanConversionClient
from constellation_control.application.run import load_scenario
from constellation_control.domain.digital_twin import DigitalTwinConfig, ScenarioLineage
from constellation_control.domain.models import ScenarioConfig


class GlonassAuthorityRequest(BaseModel):
    filename: str
    content_text: str
    source_scenario_name: str
    satellite_id: str
    slot: int


class GlonassCreateRequest(GlonassAuthorityRequest):
    target_scenario_name: str
    new_scenario_id: str


def _source(root: Path, request: GlonassAuthorityRequest):
    source = load_scenario(root / request.source_scenario_name)
    satellite = next((item for item in source.constellation.satellites if item.satellite_id == request.satellite_id), None)
    if satellite is None:
        raise ValueError(f"unknown satellite_id: {request.satellite_id}")
    if not source.orekit_sidecar_url:
        raise ValueError("selected scenario has no orekit_sidecar_url; GLONASS almanac authority is unavailable")
    return source, satellite


def _record(request: GlonassAuthorityRequest) -> tuple[object, GlonassAuthorityRecord]:
    parsed = parse_glonass_authority_source(request.filename, request.content_text)
    record = next((item for item in parsed.records if item.slot == request.slot), None)
    if record is None:
        raise ValueError(f"unknown GLONASS slot: {request.slot}")
    return parsed, record


def _authority(root: Path, request: GlonassAuthorityRequest):
    parsed, record = _record(request)
    source, satellite = _source(root, request)
    result = OrekitGlonassAlmanacMeanConversionClient(source.orekit_sidecar_url).convert(
        source_name=parsed.source_filename,
        slot=record.slot,
        frequency_channel=record.frequency_channel,
        health=record.health,
        reference_date=record.reference_date,
        reference_time_s=record.reference_time_s,
        lambda_rad=record.lambda_rad,
        delta_i_rad=record.delta_i_rad,
        argument_of_perigee_rad=record.argument_of_perigee_rad,
        eccentricity=record.eccentricity,
        delta_t_s=record.delta_t_s,
        delta_t_dot=record.delta_t_dot,
        glo_to_utc_s=record.glo_to_utc_s,
        gps_to_glo_s=record.gps_to_glo_s,
        glo_time_offset_s=record.glo_time_offset_s,
        frame=source.frame,
        target_epoch=source.epoch,
        target_time_scale=source.time_scale,
        spacecraft=satellite.spacecraft,
        force_model=source.force_model,
    )
    if result.backend_metadata.get("glonass_slot") != str(request.slot):
        raise RuntimeError("Orekit GLONASS authority returned a different slot")
    return parsed, record, source, satellite, result


def preview_glonass_authority(root: Path, request: GlonassAuthorityRequest) -> dict[str, object]:
    parsed, record, source, satellite, result = _authority(root, request)
    return {
        "valid": True,
        "source_scenario_id": source.scenario_id,
        "source_config_hash": source.config_hash(),
        "source_format": parsed.source_format,
        "source_filename": parsed.source_filename,
        "source_sha256": parsed.source_sha256,
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


def create_glonass_derived_scenario(root: Path, request: GlonassCreateRequest) -> dict[str, object]:
    parsed, record, source, satellite, result = _authority(root, request)
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
                transformation="glonass_almanac_import",
                random_seed=None,
                source_type="glonass_authority_v1",
                source_name=parsed.source_filename,
                source_sha256=parsed.source_sha256,
                source_record_id=str(record.slot),
                authority=result.backend_metadata.get("source_authority", "GLONASS-ALMANAC-OREKIT-ANALYTICAL"),
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
        "slot": record.slot,
        "parent_scenario_id": source.scenario_id,
        "parent_config_hash": source.config_hash(),
        "child_config_hash": child.config_hash(),
        "source_format": parsed.source_format,
        "source_filename": parsed.source_filename,
        "source_sha256": parsed.source_sha256,
        "backend_metadata": result.backend_metadata,
    }


GLONASS_ALMANAC_CARD = r"""
<div class="card" id="glonassAlmanacCard">
  <h3>GLONASS almanac authority</h3>
  <p class="hint">Только authority-ready labelled v1: explicit date/time, ΔT/ΔTdot и time corrections → Orekit GLONASSAnalyticalPropagator@parent epoch → osculating PV → DSST mean. Legacy preview format здесь не повышается.</p>
  <label>Файл / File <input id="gloAuthorityFile" type="file" accept=".txt"></label>
  <button onclick="previewGlonassSource()">Проверить authority source / Validate source</button>
  <div class="grid"><label>Slot <select id="gloAuthoritySlot"></select></label><label>КА сценария / Scenario satellite <select id="gloAuthoritySat"></select></label></div>
  <button onclick="previewGlonassAuthority()">Проверить через Orekit / Preview via Orekit</button>
  <pre id="gloAuthorityPreview"></pre>
  <label>Новый scenario_id <input id="gloAuthorityScenarioId" type="text" placeholder="derived-glonass-almanac-01"></label>
  <label>Новый YAML <input id="gloAuthorityScenarioFile" type="text" placeholder="derived-glonass-almanac-01.yaml"></label>
  <button onclick="createGlonassScenario()">Создать производный сценарий / Create derived scenario</button>
  <div id="gloAuthorityStatus" class="status"></div>
</div>
"""

GLONASS_ALMANAC_SCRIPT = r"""
let gloAuthorityLast=null;
function syncGlonassAuthoritySatellites(){if(!current)return;const sats=((current.normalized||current).constellation||{}).satellites||[];gloAuthoritySat.replaceChildren(...sats.map(s=>{const o=document.createElement('option');o.value=s.satellite_id;o.textContent=s.satellite_id;return o;}));}
async function previewGlonassSource(){const file=gloAuthorityFile.files&&gloAuthorityFile.files[0];if(!file){gloAuthorityStatus.textContent='Выберите authority-ready GLONASS file';gloAuthorityStatus.className='status danger';return;}const text=await file.text();const r=await fetch('/api/glonass-almanac/source-preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({filename:file.name,content_text:text})});const d=await r.json();if(!r.ok){gloAuthorityStatus.textContent=d.detail||'GLONASS source validation failed';gloAuthorityStatus.className='status danger';return;}gloAuthorityLast={filename:file.name,content_text:text};gloAuthoritySlot.replaceChildren(...d.records.map(x=>{const o=document.createElement('option');o.value=String(x.slot);o.textContent='Slot '+x.slot+' / ch '+x.frequency_channel;return o;}));gloAuthorityPreview.textContent=JSON.stringify(d,null,2);gloAuthorityStatus.textContent='AUTHORITY SOURCE VALID: records='+d.records.length;gloAuthorityStatus.className='status ok';}
function glonassAuthorityPayload(){if(!gloAuthorityLast)throw new Error('validate authority source first');if(!gloAuthoritySlot.value)throw new Error('GLONASS slot is required');if(!gloAuthoritySat.value)throw new Error('scenario satellite is required');return {filename:gloAuthorityLast.filename,content_text:gloAuthorityLast.content_text,source_scenario_name:scenario.value,satellite_id:gloAuthoritySat.value,slot:Number(gloAuthoritySlot.value)};}
async function previewGlonassAuthority(){let p;try{p=glonassAuthorityPayload();}catch(e){gloAuthorityStatus.textContent=String(e.message||e);gloAuthorityStatus.className='status danger';return;}gloAuthorityStatus.textContent='Orekit GLONASS authority…';const r=await fetch('/api/glonass-almanac/authority',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)});const d=await r.json();if(!r.ok){gloAuthorityStatus.textContent=d.detail||'GLONASS authority failed';gloAuthorityStatus.className='status danger';return;}gloAuthorityPreview.textContent=JSON.stringify(d,null,2);gloAuthorityStatus.textContent='AUTHORITY VALID: '+d.backend_metadata.source_authority+'; target='+d.target_scenario_epoch;gloAuthorityStatus.className='status ok';}
async function createGlonassScenario(){let base;try{base=glonassAuthorityPayload();}catch(e){gloAuthorityStatus.textContent=String(e.message||e);gloAuthorityStatus.className='status danger';return;}const p={...base,new_scenario_id:gloAuthorityScenarioId.value.trim(),target_scenario_name:gloAuthorityScenarioFile.value.trim()};if(!p.new_scenario_id||!p.target_scenario_name){gloAuthorityStatus.textContent='Укажите новый scenario_id и YAML';gloAuthorityStatus.className='status danger';return;}const r=await fetch('/api/glonass-almanac/create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)});const d=await r.json();if(!r.ok){gloAuthorityStatus.textContent=d.detail||'Create failed';gloAuthorityStatus.className='status danger';return;}const c=await fetch('/api/scenarios');catalog=await c.json();scenario.replaceChildren(...catalog.scenarios.map(x=>{const o=document.createElement('option');o.value=x;o.textContent=x;return o;}));scenario.value=d.scenario_name;await loadScenario();gloAuthorityStatus.textContent='Создан: '+d.scenario_name;gloAuthorityStatus.className='status ok';}
"""


def install_glonass_almanac_routes(app: FastAPI, scenario_root: Path = Path("scenarios")) -> None:
    @app.post("/api/glonass-almanac/source-preview")
    def source_preview(request: BaseModel) -> dict[str, object]:
        raise AssertionError("unreachable")

    app.router.routes.pop()

    class SourceRequest(BaseModel):
        filename: str
        content_text: str

    @app.post("/api/glonass-almanac/source-preview")
    def source_preview_typed(request: SourceRequest) -> dict[str, object]:
        try:
            return parse_glonass_authority_source(request.filename, request.content_text).model_dump(mode="json")
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/glonass-almanac/authority")
    def authority(request: GlonassAuthorityRequest) -> dict[str, object]:
        try:
            return preview_glonass_authority(scenario_root, request)
        except (ValueError, TypeError, RuntimeError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/glonass-almanac/create")
    def create(request: GlonassCreateRequest) -> dict[str, object]:
        try:
            return create_glonass_derived_scenario(scenario_root, request)
        except (ValueError, TypeError, RuntimeError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
