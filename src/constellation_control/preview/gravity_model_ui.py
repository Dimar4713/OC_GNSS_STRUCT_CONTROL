from __future__ import annotations

from math import acos, atan2, pi, sqrt
from pathlib import Path

import yaml
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, model_validator

from constellation_control.adapters.orekit.adapter import OrekitSidecarPropagator
from constellation_control.adapters.orekit.mean_conversion import (
    OrekitMeanConversionClient,
    OsculatingKeplerianElements,
)
from constellation_control.application.run import load_scenario
from constellation_control.domain.digital_twin import DigitalTwinConfig, ScenarioLineage
from constellation_control.domain.models import PropagationRequest, ScenarioConfig
from constellation_control.preview.base_preview_shell import preview_catalog


class GravityModelCreateRequest(BaseModel):
    source_scenario_name: str
    target_scenario_name: str
    new_scenario_id: str
    gravity_degree: int = Field(ge=0, le=32)
    gravity_order: int = Field(ge=0, le=32)

    @model_validator(mode="after")
    def validate_degree_order(self) -> GravityModelCreateRequest:
        if self.gravity_order > self.gravity_degree:
            raise ValueError("gravity_order must not exceed gravity_degree")
        if self.gravity_degree == 0 and self.gravity_order != 0:
            raise ValueError("Kepler mode requires degree=0 and order=0")
        return self


class GravityWorkflowError(ValueError):
    def __init__(self, code: str, ru: str, en: str, satellites: tuple[str, ...] = ()) -> None:
        super().__init__(en)
        self.code = code
        self.ru = ru
        self.en = en
        self.satellites = satellites

    def detail(self) -> dict[str, object]:
        return {"code": self.code, "ru": self.ru, "en": self.en, "satellites": list(self.satellites)}


def _target(root: Path, name: str) -> Path:
    if not name or Path(name).name != name or not name.lower().endswith((".yaml", ".yml")):
        raise GravityWorkflowError(
            "invalid_target_name",
            "Имя нового сценария должно быть новым YAML-файлом без компонентов пути.",
            "target_scenario_name must be a new YAML file name without path components",
        )
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = (root / name).resolve()
    if target.parent != root:
        raise GravityWorkflowError("invalid_target_path", "Некорректный путь нового сценария.", "invalid target scenario path")
    if target.exists():
        raise GravityWorkflowError(
            "target_exists",
            "Файл нового сценария уже существует. Перезапись исходных/производных сценариев запрещена.",
            "target scenario already exists; overwrite is forbidden",
        )
    return target


def gravity_model_label(degree: int, order: int) -> str:
    if degree == 0 and order == 0:
        return "KEPLER"
    if degree == 2 and order == 0:
        return "J2 / EIGEN-6S 2x0"
    return f"EIGEN-6S {degree}x{order}"


def _cross(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _dot(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _norm(a: tuple[float, float, float]) -> float:
    return sqrt(_dot(a, a))


def _angle_0_2pi(y: float, x: float) -> float:
    value = atan2(y, x)
    return value + 2.0 * pi if value < 0.0 else value


def cartesian_to_osculating_keplerian(
    r_m: tuple[float, float, float],
    v_m_s: tuple[float, float, float],
    mu_m3_s2: float,
) -> OsculatingKeplerianElements:
    r = _norm(r_m)
    v2 = _dot(v_m_s, v_m_s)
    if r <= 0.0 or mu_m3_s2 <= 0.0:
        raise ValueError("invalid Cartesian state or gravitational parameter")
    h_vec = _cross(r_m, v_m_s)
    h = _norm(h_vec)
    if h <= 0.0:
        raise ValueError("degenerate Cartesian orbit: angular momentum is zero")
    n_vec = (-h_vec[1], h_vec[0], 0.0)
    n = _norm(n_vec)
    rv = _dot(r_m, v_m_s)
    factor = v2 - mu_m3_s2 / r
    e_vec = (
        (factor * r_m[0] - rv * v_m_s[0]) / mu_m3_s2,
        (factor * r_m[1] - rv * v_m_s[1]) / mu_m3_s2,
        (factor * r_m[2] - rv * v_m_s[2]) / mu_m3_s2,
    )
    e = _norm(e_vec)
    energy = 0.5 * v2 - mu_m3_s2 / r
    if energy >= 0.0:
        raise ValueError("gravity-model re-derivation supports bound elliptic states only")
    a_m = -mu_m3_s2 / (2.0 * energy)
    i_rad = acos(max(-1.0, min(1.0, h_vec[2] / h)))
    eps = 1.0e-11
    raan_rad = _angle_0_2pi(n_vec[1], n_vec[0]) if n > eps else 0.0

    if e > eps:
        if n > eps:
            cos_pa = max(-1.0, min(1.0, _dot(n_vec, e_vec) / (n * e)))
            sin_pa = _dot(_cross(n_vec, e_vec), h_vec) / (n * e * h)
            pa_rad = _angle_0_2pi(sin_pa, cos_pa)
        else:
            pa_rad = _angle_0_2pi(e_vec[1], e_vec[0])
        cos_nu = max(-1.0, min(1.0, _dot(e_vec, r_m) / (e * r)))
        sin_nu = _dot(_cross(e_vec, r_m), h_vec) / (e * r * h)
        anomaly_rad = _angle_0_2pi(sin_nu, cos_nu)
    else:
        pa_rad = 0.0
        if n > eps:
            cos_u = max(-1.0, min(1.0, _dot(n_vec, r_m) / (n * r)))
            sin_u = _dot(_cross(n_vec, r_m), h_vec) / (n * r * h)
            anomaly_rad = _angle_0_2pi(sin_u, cos_u)
        else:
            anomaly_rad = _angle_0_2pi(r_m[1], r_m[0])

    return OsculatingKeplerianElements(
        a_m=a_m,
        e=e,
        i_rad=i_rad,
        pa_rad=pa_rad,
        raan_rad=raan_rad,
        anomaly_rad=anomaly_rad,
        anomaly_type="true",
    )


def _rederive_mean_elements(source: ScenarioConfig, target_force_model) -> tuple:
    source_fingerprint = source.force_model.fingerprint()
    target_fingerprint = target_force_model.fingerprint()
    if source_fingerprint == target_fingerprint:
        return source.constellation.satellites

    mismatched_source = tuple(
        sat.satellite_id
        for sat in source.constellation.satellites
        if sat.mean_orbit.definition.force_model_fingerprint != source_fingerprint
    )
    if mismatched_source:
        ids_preview = ", ".join(mismatched_source[:5]) + ("..." if len(mismatched_source) > 5 else "")
        raise GravityWorkflowError(
            "source_mean_fingerprint_mismatch",
            f"Средние элементы исходного сценария уже не согласованы с его моделью сил ({ids_preview}). Смена ГПЗ заблокирована до восстановления исходной authority.",
            f"source scenario mean elements already disagree with its own force model ({ids_preview}); gravity change is blocked until source authority is restored",
            mismatched_source,
        )
    if not source.orekit_sidecar_url:
        all_satellite_ids = tuple(sat.satellite_id for sat in source.constellation.satellites)
        raise GravityWorkflowError(
            "orekit_required_for_rederive",
            "Для смены модели ГПЗ требуется Orekit authority: программа должна восстановить оскулирующее состояние из старых DSST mean и заново получить mean для новой модели сил.",
            "Orekit authority is required to change the gravity model: the application must reconstruct the epoch osculating state from the old DSST mean elements and derive new mean elements for the requested force model.",
            all_satellite_ids,
        )
    unsupported = tuple(
        sat.satellite_id
        for sat in source.constellation.satellites
        if not sat.mean_orbit.definition.theory.startswith("orekit-dsst-")
    )
    if unsupported:
        ids_preview = ", ".join(unsupported[:5]) + ("..." if len(unsupported) > 5 else "")
        raise GravityWorkflowError(
            "non_dsst_mean_rederive_unsupported",
            f"Автоматический пересчёт ГПЗ безопасен только для DSST mean elements. Для {ids_preview} требуется authoritative оскулирующий/TLE/GNSS источник.",
            f"automatic gravity-model re-derivation is safe only for DSST mean elements; {ids_preview} requires an authoritative osculating/TLE/GNSS source",
            unsupported,
        )

    probe_duration_s = 1.0e-3
    probe = PropagationRequest(
        scenario_id=f"{source.scenario_id}-gravity-rebind-probe",
        epoch=source.epoch,
        frame=source.frame,
        time_scale=source.time_scale,
        satellites=source.constellation.satellites,
        maneuvers=(),
        duration_s=probe_duration_s,
        output_step_s=probe_duration_s,
        force_model=source.force_model,
        integrator=source.integrator,
        seed=source.seed,
    )
    try:
        propagated = OrekitSidecarPropagator(source.orekit_sidecar_url, timeout_s=180.0).propagate(probe)
        converter = OrekitMeanConversionClient(source.orekit_sidecar_url, timeout_s=60.0)
        rebound = []
        for satellite in source.constellation.satellites:
            states = propagated.cartesian_states.get(satellite.satellite_id)
            if not states:
                raise RuntimeError(f"Orekit gravity rebind probe returned no osculating state for {satellite.satellite_id}")
            state = states[0]
            elements = cartesian_to_osculating_keplerian(state.r_m, state.v_m_s, source.force_model.mu_m3_s2)
            converted = converter.convert(
                epoch=source.epoch,
                frame=source.frame,
                time_scale=source.time_scale,
                elements=elements,
                spacecraft=satellite.spacecraft,
                force_model=target_force_model,
            )
            if converted.mean_orbit.definition.force_model_fingerprint != target_fingerprint:
                raise RuntimeError(f"Orekit gravity rebind returned wrong fingerprint for {satellite.satellite_id}")
            rebound.append(satellite.model_copy(update={"mean_orbit": converted.mean_orbit}))
        return tuple(rebound)
    except GravityWorkflowError:
        raise
    except Exception as exc:
        raise GravityWorkflowError(
            "gravity_rederive_failed",
            f"Orekit не смог согласованно пересчитать средние элементы под новую модель ГПЗ: {exc}",
            f"Orekit failed to re-derive force-model-consistent mean elements for the requested gravity model: {exc}",
        ) from exc


def create_gravity_derived_scenario(root: Path, request: GravityModelCreateRequest) -> dict[str, object]:
    root = root.resolve()
    source = load_scenario(root / request.source_scenario_name)
    if request.new_scenario_id == source.scenario_id:
        raise GravityWorkflowError(
            "scenario_id_reused",
            "Новый scenario_id должен отличаться от scenario_id родительского сценария.",
            "new_scenario_id must differ from parent scenario_id",
        )
    target = _target(root, request.target_scenario_name)

    force_model = source.force_model.model_copy(
        update={"gravity_degree": request.gravity_degree, "gravity_order": request.gravity_order}
    )
    satellites = _rederive_mean_elements(source, force_model)
    constellation = source.constellation.model_copy(update={"satellites": satellites})

    prior_twin = source.digital_twin or DigitalTwinConfig()
    digital_twin = prior_twin.model_copy(
        update={
            "lineage": ScenarioLineage(
                parent_scenario_id=source.scenario_id,
                parent_config_hash=source.config_hash(),
                transformation="gravity_model_change",
                random_seed=None,
            )
        }
    )
    child = ScenarioConfig.model_validate(
        source.model_dump(mode="json")
        | {
            "scenario_id": request.new_scenario_id,
            "force_model": force_model.model_dump(mode="json"),
            "constellation": constellation.model_dump(mode="json"),
            "digital_twin": digital_twin.model_dump(mode="json"),
        }
    )
    target.write_text(yaml.safe_dump(child.model_dump(mode="json"), sort_keys=False, allow_unicode=True), encoding="utf-8")

    persisted = load_scenario(target)
    catalog = preview_catalog(root)
    runnable_value = catalog.get("scenarios", [])
    if not isinstance(runnable_value, list) or not all(isinstance(item, str) for item in runnable_value):
        raise GravityWorkflowError(
            "invalid_catalog",
            "Каталог сценариев вернул некорректный список запускаемых сценариев.",
            "scenario catalog returned an invalid runnable scenario list",
        )
    runnable = [item for item in runnable_value if isinstance(item, str)]
    if target.name not in runnable:
        raise GravityWorkflowError(
            "derived_not_runnable",
            "Производный сценарий сохранён, но не распознан как запускаемый ScenarioConfig.",
            "derived scenario was saved but is not discoverable as a runnable ScenarioConfig",
        )

    return {
        "saved": True,
        "scenario_name": target.name,
        "scenario_id": persisted.scenario_id,
        "parent_scenario_id": source.scenario_id,
        "gravity_degree": request.gravity_degree,
        "gravity_order": request.gravity_order,
        "gravity_label": gravity_model_label(request.gravity_degree, request.gravity_order),
        "force_model_fingerprint": persisted.force_model.fingerprint(),
        "child_config_hash": persisted.config_hash(),
        "mean_elements_rederived": source.force_model.fingerprint() != persisted.force_model.fingerprint(),
        "catalog": catalog,
    }


GRAVITY_MODEL_CARD = r"""
<div class="card" id="gravityModelCard">
  <h3 data-gravity-i18n="title"></h3>
  <p class="hint" data-gravity-i18n="hint"></p>
  <div class="grid">
    <label><span data-gravity-i18n="preset"></span>
      <select id="gravityPreset" onchange="applyGravityPreset()">
        <option value="kepler">Kepler 0x0</option>
        <option value="j2">J2 / 2x0</option>
        <option value="4">EIGEN-6S 4x4</option>
        <option value="8" selected>EIGEN-6S 8x8</option>
        <option value="12">EIGEN-6S 12x12</option>
        <option value="16">EIGEN-6S 16x16</option>
        <option value="24">EIGEN-6S 24x24</option>
        <option value="32">EIGEN-6S 32x32</option>
        <option value="custom">Custom</option>
      </select>
    </label>
    <label><span data-gravity-i18n="degree"></span> <input id="gravityDegree" type="number" min="0" max="32" step="1" value="8"></label>
    <label><span data-gravity-i18n="order"></span> <input id="gravityOrder" type="number" min="0" max="32" step="1" value="8"></label>
  </div>
  <div id="gravityCurrent" class="status"></div>
  <label><span data-gravity-i18n="newScenarioId"></span> <input id="gravityScenarioId" type="text" placeholder="derived-gravity-32x32"></label>
  <label><span data-gravity-i18n="newYaml"></span> <input id="gravityScenarioFile" type="text" placeholder="derived-gravity-32x32.yaml"></label>
  <button id="gravityCreateBtn" onclick="createGravityScenario()"></button>
  <div id="gravityStatus" class="status"></div>
</div>
"""

GRAVITY_MODEL_SCRIPT = r"""
const GT={ru:{title:'Модель ГПЗ',hint:'Явный выбор сложности гравитационного поля. При смене ГПЗ программа сохраняет физическое оскулирующее состояние на эпохе: старые DSST mean → Orekit osculating → новые DSST mean под выбранную модель сил. Простая подмена fingerprint запрещена.',preset:'Предустановка',degree:'Степень n',order:'Порядок m',newScenarioId:'Новый scenario_id',newYaml:'Новый YAML',create:'Создать запускаемый производный сценарий',current:'Текущая модель',fingerprint:'fingerprint',invalidRange:'Требуется 0 <= порядок <= степень <= 32',requiredNames:'Укажите новый scenario_id и YAML',checking:'Orekit: согласование mean elements и создание сценария…',created:'Создан',rederived:'средние элементы пересчитаны под новую модель сил',createFailed:'Не удалось создать сценарий'},en:{title:'Earth gravity model',hint:'Explicit gravity-field fidelity selection. When gravity changes, the application preserves the physical osculating state at the epoch: old DSST mean → Orekit osculating → new DSST mean for the requested force model. Fingerprint substitution is forbidden.',preset:'Preset',degree:'Degree n',order:'Order m',newScenarioId:'New scenario_id',newYaml:'New YAML',create:'Create runnable derived scenario',current:'Current model',fingerprint:'fingerprint',invalidRange:'Required: 0 <= order <= degree <= 32',requiredNames:'Specify a new scenario_id and YAML',checking:'Orekit: re-deriving mean elements and creating scenario…',created:'Created',rederived:'mean elements re-derived for the requested force model',createFailed:'Scenario creation failed'}};
function gravityTr(k){return (GT[lang]||GT.ru)[k]||k;}
function renderGravityLanguage(){document.querySelectorAll('[data-gravity-i18n]').forEach(e=>e.textContent=gravityTr(e.dataset.gravityI18n));if(window.gravityCreateBtn)gravityCreateBtn.textContent=gravityTr('create');syncGravityModel();}
const _gravityBaseRenderLanguage=renderLanguage;renderLanguage=function(){_gravityBaseRenderLanguage();renderGravityLanguage();};
function gravityErrorText(d){const detail=d&&d.detail;if(detail&&typeof detail==='object'&&(detail.ru||detail.en))return lang==='ru'?(detail.ru||detail.en):(detail.en||detail.ru);if(typeof detail==='string')return detail;return gravityTr('createFailed');}
function applyGravityPreset(){const v=gravityPreset.value;if(v==='kepler'){gravityDegree.value=0;gravityOrder.value=0;}else if(v==='j2'){gravityDegree.value=2;gravityOrder.value=0;}else if(v!=='custom'){gravityDegree.value=Number(v);gravityOrder.value=Number(v);}}
function syncGravityModel(){if(!current)return;const f=(current.normalized||current).force_model||{};gravityDegree.value=f.gravity_degree;gravityOrder.value=f.gravity_order;gravityCurrent.textContent=gravityTr('current')+': '+(f.gravity_degree===0&&f.gravity_order===0?'Kepler':('EIGEN-6S '+f.gravity_degree+'x'+f.gravity_order))+'; '+gravityTr('fingerprint')+'='+((current.force_model_fingerprint)||'');}
async function createGravityScenario(){const n=Number(gravityDegree.value),m=Number(gravityOrder.value);if(!Number.isInteger(n)||!Number.isInteger(m)||n<0||m<0||n>32||m>32||m>n){gravityStatus.textContent=gravityTr('invalidRange');gravityStatus.className='status danger';return;}const p={source_scenario_name:scenario.value,target_scenario_name:gravityScenarioFile.value.trim(),new_scenario_id:gravityScenarioId.value.trim(),gravity_degree:n,gravity_order:m};if(!p.target_scenario_name||!p.new_scenario_id){gravityStatus.textContent=gravityTr('requiredNames');gravityStatus.className='status danger';return;}gravityStatus.textContent=gravityTr('checking');gravityStatus.className='status';const r=await fetch('/api/gravity-model/create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)});const d=await r.json();if(!r.ok){gravityStatus.textContent=gravityErrorText(d);gravityStatus.className='status danger';return;}catalog=d.catalog;scenario.replaceChildren(...catalog.scenarios.map(x=>{const o=document.createElement('option');o.value=x;o.textContent=x;return o;}));renderOther();scenario.value=d.scenario_name;await loadScenario();gravityStatus.textContent=gravityTr('created')+': '+d.scenario_name+'; '+d.gravity_label+(d.mean_elements_rederived?'; '+gravityTr('rederived'):'');gravityStatus.className='status ok';}
"""


def install_gravity_model_routes(app: FastAPI, scenario_root: Path) -> None:
    scenario_root = scenario_root.resolve()

    @app.post("/api/gravity-model/create")
    def create(request: GravityModelCreateRequest) -> dict[str, object]:
        try:
            return create_gravity_derived_scenario(scenario_root, request)
        except GravityWorkflowError as exc:
            raise HTTPException(status_code=422, detail=exc.detail()) from exc
        except (ValueError, TypeError, RuntimeError, OSError) as exc:
            detail = {
                "code": "gravity_model_error",
                "ru": f"Не удалось изменить модель ГПЗ: {exc}",
                "en": f"Failed to change the gravity model: {exc}",
                "satellites": [],
            }
            raise HTTPException(status_code=422, detail=detail) from exc
