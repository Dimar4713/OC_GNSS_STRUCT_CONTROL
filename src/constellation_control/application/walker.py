from __future__ import annotations

import math
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator

from constellation_control.application.run import load_scenario
from constellation_control.domain.digital_twin import DigitalTwinConfig, ScenarioLineage
from constellation_control.domain.models import ConstellationSpec, MeanElementDefinition, MeanOrbit, PlaneSpec, SatelliteSpec, ScenarioConfig


class WalkerDeltaRequest(BaseModel):
    source_scenario_name: str
    target_scenario_name: str
    new_scenario_id: str
    template_satellite_id: str
    total_satellites: int = Field(gt=0)
    planes: int = Field(gt=0)
    phasing: int = Field(ge=0)
    semi_major_axis_m: float = Field(gt=0.0)
    eccentricity: float = Field(ge=0.0, lt=1.0)
    inclination_deg: float = Field(ge=0.0, lt=180.0)
    raan0_deg: float
    argument_of_perigee_deg: float
    mean_anomaly0_deg: float

    @model_validator(mode="after")
    def validate_walker(self) -> WalkerDeltaRequest:
        if self.total_satellites % self.planes != 0:
            raise ValueError("Walker Delta requires total_satellites divisible by planes")
        if self.phasing >= self.total_satellites:
            raise ValueError("phasing must be less than total_satellites")
        return self


def _safe_new_yaml_path(root: Path, name: str) -> Path:
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


def _equinoctial_mean_orbit(
    *,
    a_m: float,
    e: float,
    i_rad: float,
    raan_rad: float,
    argument_of_perigee_rad: float,
    mean_anomaly_rad: float,
    force_fingerprint: str,
) -> MeanOrbit:
    longitude_of_perigee = raan_rad + argument_of_perigee_rad
    ex = e * math.cos(longitude_of_perigee)
    ey = e * math.sin(longitude_of_perigee)
    t = math.tan(i_rad / 2.0)
    ix = t * math.cos(raan_rad)
    iy = t * math.sin(raan_rad)
    lam = (longitude_of_perigee + mean_anomaly_rad) % (2.0 * math.pi)
    return MeanOrbit(
        a_m=a_m,
        ex=ex,
        ey=ey,
        ix=ix,
        iy=iy,
        lambda_rad=lam,
        definition=MeanElementDefinition(
            theory="walker-delta-engineering-mean-input",
            force_model_fingerprint=force_fingerprint,
        ),
    )


def build_walker_constellation(source: ScenarioConfig, request: WalkerDeltaRequest) -> ConstellationSpec:
    template = next((sat for sat in source.constellation.satellites if sat.satellite_id == request.template_satellite_id), None)
    if template is None:
        raise ValueError(f"unknown template_satellite_id: {request.template_satellite_id}")

    per_plane = request.total_satellites // request.planes
    force_fingerprint = source.force_model.fingerprint()
    satellites: list[SatelliteSpec] = []
    planes: list[PlaneSpec] = []
    first_id = "W-P01-S01"
    argument_of_perigee_rad = math.radians(request.argument_of_perigee_deg)

    for plane_index in range(request.planes):
        plane_id = f"W-P{plane_index + 1:02d}"
        member_ids: list[str] = []
        raan_deg = request.raan0_deg + 360.0 * plane_index / request.planes
        for slot_index in range(per_plane):
            satellite_id = f"W-P{plane_index + 1:02d}-S{slot_index + 1:02d}"
            member_ids.append(satellite_id)
            mean_anomaly_deg = (
                request.mean_anomaly0_deg
                + 360.0 * slot_index / per_plane
                + 360.0 * request.phasing * plane_index / request.total_satellites
            )
            satellites.append(
                SatelliteSpec(
                    satellite_id=satellite_id,
                    plane_id=plane_id,
                    role="reference" if satellite_id == first_id else "additional",
                    reference_id=None if satellite_id == first_id else first_id,
                    mean_orbit=_equinoctial_mean_orbit(
                        a_m=request.semi_major_axis_m,
                        e=request.eccentricity,
                        i_rad=math.radians(request.inclination_deg),
                        raan_rad=math.radians(raan_deg % 360.0),
                        argument_of_perigee_rad=argument_of_perigee_rad,
                        mean_anomaly_rad=math.radians(mean_anomaly_deg % 360.0),
                        force_fingerprint=force_fingerprint,
                    ),
                    spacecraft=template.spacecraft,
                )
            )
        planes.append(PlaneSpec(plane_id=plane_id, satellite_ids=tuple(member_ids)))

    return ConstellationSpec(satellites=tuple(satellites), planes=tuple(planes))


def create_walker_derived_scenario(scenario_root: Path, request: WalkerDeltaRequest) -> dict[str, object]:
    source_path = scenario_root / request.source_scenario_name
    source = load_scenario(source_path)
    if request.new_scenario_id == source.scenario_id:
        raise ValueError("new_scenario_id must differ from parent scenario_id")
    target = _safe_new_yaml_path(scenario_root, request.target_scenario_name)

    constellation = build_walker_constellation(source, request)
    payload = source.model_dump(mode="json")
    payload["scenario_id"] = request.new_scenario_id
    payload["constellation"] = constellation.model_dump(mode="json")
    payload["maneuvers"] = []
    payload["digital_twin"] = DigitalTwinConfig(
        lineage=ScenarioLineage(
            parent_scenario_id=source.scenario_id,
            parent_config_hash=source.config_hash(),
            transformation="walker_generation",
            random_seed=None,
        )
    ).model_dump(mode="json")
    child = ScenarioConfig.model_validate(payload)
    target.write_text(yaml.safe_dump(child.model_dump(mode="json"), sort_keys=False, allow_unicode=True), encoding="utf-8")
    return {
        "saved": True,
        "scenario_name": target.name,
        "scenario_id": child.scenario_id,
        "parent_scenario_id": source.scenario_id,
        "parent_config_hash": source.config_hash(),
        "child_config_hash": child.config_hash(),
        "satellite_count": len(child.constellation.satellites),
        "plane_count": len(child.constellation.planes),
    }
