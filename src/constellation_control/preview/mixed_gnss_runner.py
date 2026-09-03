from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

import yaml
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, model_validator

from constellation_control.adapters.gnss_almanac import (
    GnssAlmanacFormat,
    GpsSemRecord,
    GpsYumaRecord,
    preview_gnss_almanac,
)
from constellation_control.adapters.iac_glonass_almanac import normalize_iac_glonass_almanac
from constellation_control.adapters.iac_glonass_authority_bridge import (
    IacGlonassAuthoritySupplement,
    iac_glonass_to_authority_record,
)
from constellation_control.adapters.iac_gnss_tables import IacDataset, fetch_iac_table
from constellation_control.adapters.orekit.mean_conversion import (
    OrekitGlonassAlmanacMeanConversionClient,
    OrekitGpsAlmanacMeanConversionClient,
)
from constellation_control.application.run import load_scenario
from constellation_control.domain.digital_twin import DigitalTwinConfig, ScenarioLineage
from constellation_control.domain.models import ConstellationSpec, SatelliteSpec, ScenarioConfig
from constellation_control.preview.navcen_gps_runner import fetch_navcen_gps_almanac


class MixedGnssBuildRequest(BaseModel):
    source_scenario_name: str
    template_satellite_id: str
    gps_source_format: Literal["yuma", "sem"]
    gps_selection: Literal["healthy-only", "all"]
    glonass_health: int
    glo_to_utc_s: float
    gps_to_glo_s: float
    glo_time_offset_s: float
    target_scenario_name: str
    new_scenario_id: str

    @model_validator(mode="after")
    def validate_health(self) -> MixedGnssBuildRequest:
        if self.glonass_health < 0:
            raise ValueError("glonass_health must be non-negative")
        return self


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


def _gps_format(value: Literal["yuma", "sem"]) -> GnssAlmanacFormat:
    return GnssAlmanacFormat.GPS_YUMA if value == "yuma" else GnssAlmanacFormat.GPS_SEM


def _gps_sidecar_format(value: Literal["yuma", "sem"]) -> Literal["gps-yuma", "gps-sem"]:
    return "gps-yuma" if value == "yuma" else "gps-sem"


def _gps_health(record: GpsYumaRecord | GpsSemRecord) -> int:
    return record.health


def _source(root: Path, request: MixedGnssBuildRequest):
    source = load_scenario(root / request.source_scenario_name)
    template = next(
        (item for item in source.constellation.satellites if item.satellite_id == request.template_satellite_id),
        None,
    )
    if template is None:
        raise ValueError(f"unknown template_satellite_id: {request.template_satellite_id}")
    if not source.orekit_sidecar_url:
        raise ValueError("selected scenario has no orekit_sidecar_url; mixed GNSS authority is unavailable")
    return source, template


def build_mixed_gnss_scenario(root: Path, request: MixedGnssBuildRequest) -> dict[str, object]:
    source, template = _source(root, request)
    if request.new_scenario_id == source.scenario_id:
        raise ValueError("new_scenario_id must differ from parent scenario_id")
    target = _target(root, request.target_scenario_name)

    glo_table = fetch_iac_table(IacDataset.GLONASS_ALMANAC)
    glo_almanac = normalize_iac_glonass_almanac(glo_table)
    if not glo_almanac.records:
        raise ValueError("IAC GLONASS almanac contains no records")

    gps_url, gps_text, gps_raw_sha = fetch_navcen_gps_almanac(request.gps_source_format)
    gps_preview = preview_gnss_almanac(Path(gps_url).name, gps_text, _gps_format(request.gps_source_format))
    if gps_preview.source_sha256 != gps_raw_sha:
        raise RuntimeError("NAVCEN GPS source hash changed during parsing")
    gps_records = tuple(
        record
        for record in gps_preview.records
        if isinstance(record, (GpsYumaRecord, GpsSemRecord))
        and (request.gps_selection == "all" or _gps_health(record) == 0)
    )
    if not gps_records:
        raise ValueError("NAVCEN GPS selection contains no records")

    glo_client = OrekitGlonassAlmanacMeanConversionClient(source.orekit_sidecar_url)
    gps_client = OrekitGpsAlmanacMeanConversionClient(source.orekit_sidecar_url)
    supplement = IacGlonassAuthoritySupplement(
        health=request.glonass_health,
        glo_to_utc_s=request.glo_to_utc_s,
        gps_to_glo_s=request.gps_to_glo_s,
        glo_time_offset_s=request.glo_time_offset_s,
    )
    source_name = glo_table.source_url or "IAC-GLONASS"
    satellites: list[SatelliteSpec] = []
    glo_ids: list[str] = []
    gps_ids: list[str] = []

    for record in glo_almanac.records:
        authority_record = iac_glonass_to_authority_record(record, supplement)
        result = glo_client.convert(
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
            spacecraft=template.spacecraft,
            force_model=source.force_model,
        )
        if result.backend_metadata.get("glonass_slot") != str(record.slot):
            raise RuntimeError(f"Orekit GLONASS authority returned a different slot for {record.slot}")
        satellite_id = f"GLO-{record.slot:02d}"
        glo_ids.append(satellite_id)
        satellites.append(
            SatelliteSpec(
                satellite_id=satellite_id,
                plane_id="ALMANAC-UNASSIGNED",
                role="reference",
                mean_orbit=result.mean_orbit,
                spacecraft=template.spacecraft,
            )
        )

    for record in gps_records:
        result = gps_client.convert(
            source_format=_gps_sidecar_format(request.gps_source_format),
            source_name=gps_url,
            source_text=gps_text,
            prn=record.prn,
            frame=source.frame,
            target_epoch=source.epoch,
            target_time_scale=source.time_scale,
            spacecraft=template.spacecraft,
            force_model=source.force_model,
        )
        if result.backend_metadata.get("gps_prn") != str(record.prn):
            raise RuntimeError(f"Orekit GPS authority returned a different PRN for {record.prn}")
        satellite_id = f"GPS-{record.prn:02d}"
        gps_ids.append(satellite_id)
        satellites.append(
            SatelliteSpec(
                satellite_id=satellite_id,
                plane_id="ALMANAC-UNASSIGNED",
                role="reference",
                mean_orbit=result.mean_orbit,
                spacecraft=template.spacecraft,
            )
        )

    manifest = {
        "iac_glonass": {
            "source_url": glo_table.source_url,
            "source_sha256": glo_table.source_sha256,
            "slots": [record.slot for record in glo_almanac.records],
            "operator_health": request.glonass_health,
            "glo_to_utc_s": request.glo_to_utc_s,
            "gps_to_glo_s": request.gps_to_glo_s,
            "glo_time_offset_s": request.glo_time_offset_s,
        },
        "navcen_gps": {
            "source_url": gps_url,
            "source_sha256": gps_preview.source_sha256,
            "format": request.gps_source_format,
            "selection": request.gps_selection,
            "prns": [record.prn for record in gps_records],
        },
        "template_satellite_id": template.satellite_id,
        "plane_assignment": "ALMANAC-UNASSIGNED",
    }
    manifest_text = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    manifest_sha = hashlib.sha256(manifest_text.encode("utf-8")).hexdigest()
    authority = (
        "MIXED-GNSS-OREKIT; "
        f"IAC_GLONASS_SHA256={glo_table.source_sha256}; "
        f"NAVCEN_GPS_SHA256={gps_preview.source_sha256}; "
        "all source records propagated to parent epoch and converted to DSST mean; "
        "spacecraft copied from explicit template_satellite_id; physical plane assignment intentionally not inferred"
    )
    prior_twin = source.digital_twin or DigitalTwinConfig()
    digital_twin = prior_twin.model_copy(
        update={
            "lineage": ScenarioLineage(
                parent_scenario_id=source.scenario_id,
                parent_config_hash=source.config_hash(),
                transformation="mixed_gnss_almanac_import",
                random_seed=None,
                source_type="mixed_gnss_almanac",
                source_name="IAC GLONASS + USCG NAVCEN GPS",
                source_sha256=manifest_sha,
                source_record_id=f"GLO:{len(glo_ids)};GPS:{len(gps_ids)}",
                authority=authority,
            )
        }
    )
    constellation = ConstellationSpec(satellites=tuple(satellites), planes=())
    child = ScenarioConfig.model_validate(
        source.model_dump(mode="json")
        | {
            "scenario_id": request.new_scenario_id,
            "constellation": constellation.model_dump(mode="json"),
            "maneuvers": [],
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
        "parent_scenario_id": source.scenario_id,
        "parent_config_hash": source.config_hash(),
        "child_config_hash": child.config_hash(),
        "satellite_count": len(satellites),
        "glonass_count": len(glo_ids),
        "gps_count": len(gps_ids),
        "glonass_satellite_ids": glo_ids,
        "gps_satellite_ids": gps_ids,
        "iac_glonass_source_url": glo_table.source_url,
        "iac_glonass_source_sha256": glo_table.source_sha256,
        "navcen_gps_source_url": gps_url,
        "navcen_gps_source_sha256": gps_preview.source_sha256,
        "source_manifest_sha256": manifest_sha,
        "template_satellite_id": template.satellite_id,
        "plane_assignment": "ALMANAC-UNASSIGNED",
    }


MIXED_GNSS_RUNNER_CARD = r"""
<div class="card" id="mixedGnssRunnerCard">
  <h3>ГЛОНАСС ИАЦ + GPS NAVCEN → полная runnable группировка</h3>
  <p class="hint">Пакетная сборка: все записи текущего ИАЦ GLONASS + выбранные записи текущего NAVCEN GPS YUMA/SEM → Orekit authority → DSST mean → один новый ScenarioConfig. Модель КА берётся только из явно выбранного template satellite. Физические плоскости по альманаху пока не выводятся: plane_id=ALMANAC-UNASSIGNED.</p>
  <div class="grid">
    <label>Шаблон КА / Spacecraft template <select id="mixedGnssTemplateSat"></select></label>
    <label>GPS source <select id="mixedGnssGpsFormat"><option value="yuma">NAVCEN current YUMA</option><option value="sem">NAVCEN current SEM</option></select></label>
  </div>
  <div class="grid">
    <label>GPS selection <select id="mixedGnssGpsSelection"><option value="healthy-only">Healthy only (health=0)</option><option value="all">All records</option></select></label>
    <label>GLONASS health applied to all IAC slots <input id="mixedGnssGloHealth" type="number" min="0" value="0"></label>
  </div>
  <div class="grid"><label>GLO→UTC, s <input id="mixedGnssGloUtc" type="number" step="any"></label><label>GPS→GLO, s <input id="mixedGnssGpsGlo" type="number" step="any"></label></div>
  <label>GLO time offset, s <input id="mixedGnssGloOffset" type="number" step="any"></label>
  <label>Новый scenario_id <input id="mixedGnssScenarioId" type="text" placeholder="current-glo-gps-almanac"></label>
  <label>Новый YAML <input id="mixedGnssScenarioFile" type="text" placeholder="current-glo-gps-almanac.yaml"></label>
  <button onclick="buildMixedGnssScenario()">Скачать альманахи и собрать всю группировку / Build full constellation</button>
  <pre id="mixedGnssResult"></pre>
  <div id="mixedGnssStatus" class="status"></div>
</div>
"""

MIXED_GNSS_RUNNER_SCRIPT = r"""
function syncMixedGnssTemplateSatellites(){if(!current)return;const sats=((current.normalized||current).constellation||{}).satellites||[];mixedGnssTemplateSat.replaceChildren(...sats.map(s=>{const o=document.createElement('option');o.value=s.satellite_id;o.textContent=s.satellite_id;return o;}));}
function mixedGnssSetStatus(t,k=''){mixedGnssStatus.textContent=t;mixedGnssStatus.className='status '+k;}
async function buildMixedGnssScenario(){
 const nums=[mixedGnssGloUtc.value,mixedGnssGpsGlo.value,mixedGnssGloOffset.value];if(nums.some(x=>x.trim()==='')){mixedGnssSetStatus('Укажите все три GLONASS time-correction authority значения','danger');return;}
 const p={source_scenario_name:scenario.value,template_satellite_id:mixedGnssTemplateSat.value,gps_source_format:mixedGnssGpsFormat.value,gps_selection:mixedGnssGpsSelection.value,glonass_health:Number(mixedGnssGloHealth.value),glo_to_utc_s:Number(mixedGnssGloUtc.value),gps_to_glo_s:Number(mixedGnssGpsGlo.value),glo_time_offset_s:Number(mixedGnssGloOffset.value),new_scenario_id:mixedGnssScenarioId.value.trim(),target_scenario_name:mixedGnssScenarioFile.value.trim()};
 if(!p.template_satellite_id||!p.new_scenario_id||!p.target_scenario_name){mixedGnssSetStatus('Выберите template satellite и укажите новый scenario_id/YAML','danger');return;}
 mixedGnssSetStatus('IAC GLONASS + NAVCEN GPS → Orekit batch conversion…');
 const r=await fetch('/api/mixed-gnss-runner/create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)});const d=await r.json();if(!r.ok){mixedGnssSetStatus(d.detail||'Mixed GNSS build failed','danger');return;}
 mixedGnssResult.textContent=JSON.stringify(d,null,2);const c=await fetch('/api/scenarios');catalog=await c.json();scenario.replaceChildren(...catalog.scenarios.map(x=>{const o=document.createElement('option');o.value=x;o.textContent=x;return o;}));scenario.value=d.scenario_name;await loadScenario();mixedGnssSetStatus('RUNNABLE: '+d.scenario_name+'; satellites='+d.satellite_count+' (GLO='+d.glonass_count+', GPS='+d.gps_count+')','ok');
}
"""


def install_mixed_gnss_runner_routes(app: FastAPI, scenario_root: Path = Path("scenarios")) -> None:
    @app.post("/api/mixed-gnss-runner/create")
    def create(request: MixedGnssBuildRequest) -> dict[str, object]:
        try:
            return build_mixed_gnss_scenario(scenario_root, request)
        except (ValueError, TypeError, RuntimeError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
