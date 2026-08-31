from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, ValidationError

from constellation_control.adapters.orekit.http import open_orekit_url
from constellation_control.application.run import load_scenario
from constellation_control.application.run_duration import run_scenario_with_duration
from constellation_control.domain.models import ForceMode, ScenarioConfig
from constellation_control.preview.duration import DURATION_PRESETS_S, predicted_output_sample_count
from constellation_control.preview.engineering import (
    constellation_geometry_preflight,
    mean_orbit_engineering_elements,
)
from constellation_control.preview.operations import preview_operations_payload

PREVIEW_VERSION = "0.1.4"
_RESULT_ARTIFACTS = {
    "11_delta_u_mean.png",
    "12_along_track_mean_arc_proxy.png",
    "interactive_delta_u_mean.html",
}


class PreviewRunRequest(BaseModel):
    scenario_name: str
    duration_preset: str | None = "scenario"
    custom_duration_s: float | None = None


def _authority_label(scenario: ScenarioConfig) -> str:
    mode = scenario.force_model.mode
    if mode == ForceMode.SCREENING:
        return "SCREENING — analytical/synthetic mean-element authority"
    if mode == ForceMode.DESIGN:
        return "DESIGN — Orekit DSST authority required"
    if mode == ForceMode.VALIDATION:
        return "VALIDATION — Orekit numerical authority required"
    raise ValueError(f"Unsupported force mode / Неподдерживаемый режим модели сил: {mode}")


def _safe_scenario_path(scenario_root: Path, scenario_name: str) -> Path:
    if not scenario_name or Path(scenario_name).name != scenario_name:
        raise ValueError(
            "Имя сценария должно быть именем YAML-файла без пути / "
            "scenario_name must be a YAML file name without path components"
        )
    if not scenario_name.lower().endswith((".yaml", ".yml")):
        raise ValueError("Требуется файл .yaml/.yml / scenario_name must end with .yaml or .yml")
    root = scenario_root.resolve()
    candidate = (root / scenario_name).resolve()
    if candidate.parent != root or not candidate.is_file():
        raise ValueError(f"Сценарий не найден / scenario not found: {scenario_name}")
    return candidate


def _safe_result_file(output_root: Path, scenario_id: str, run_id: str, name: str) -> Path:
    for component in (scenario_id, run_id, name):
        if not component or component in {".", ".."} or Path(component).name != component:
            raise ValueError("Некорректный путь результата / result path contains invalid components")
    root = output_root.resolve()
    candidate = (root / scenario_id / run_id / name).resolve()
    if root not in candidate.parents or not candidate.is_file():
        raise ValueError("Файл результата не найден / result artifact not found")
    return candidate


def _classify_yaml(path: Path) -> tuple[str, str | None]:
    try:
        load_scenario(path)
        return "scenario", None
    except (ValidationError, ValueError, TypeError) as exc:
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            return "invalid_yaml", "YAML не читается / YAML cannot be parsed"
        if isinstance(raw, dict):
            keys = set(raw)
            if {"bounds", "lhs_samples", "top_k"}.issubset(keys):
                return (
                    "design_pipeline_config",
                    "Конфигурация Design pipeline; используйте workflow Design / "
                    "Design pipeline configuration; use the Design workflow.",
                )
            if "campaign" in keys:
                return (
                    "robustness_campaign_config",
                    "Конфигурация Robustness campaign; используйте workflow Robustness / "
                    "Robustness campaign configuration; use the Robustness workflow.",
                )
        first = str(exc).splitlines()[0] if str(exc) else "not a ScenarioConfig"
        return "other_yaml", f"Не является запускаемым ScenarioConfig / Not a runnable ScenarioConfig: {first}"


def preview_catalog(scenario_root: Path) -> dict[str, object]:
    accepted: list[str] = []
    rejected: list[dict[str, str]] = []
    if not scenario_root.is_dir():
        return {"scenarios": accepted, "other_inputs": rejected}
    for path in sorted(scenario_root.iterdir(), key=lambda item: item.name):
        if not path.is_file() or path.suffix.lower() not in {".yaml", ".yml"}:
            continue
        kind, diagnostic = _classify_yaml(path)
        if kind == "scenario":
            accepted.append(path.name)
        else:
            rejected.append(
                {
                    "name": path.name,
                    "kind": kind,
                    "diagnostic": diagnostic or "Не запускаемый сценарий / not a runnable scenario",
                }
            )
    return {"scenarios": accepted, "other_inputs": rejected}


def list_preview_scenarios(scenario_root: Path) -> list[str]:
    return list(cast(list[str], preview_catalog(scenario_root)["scenarios"]))


def _load_preview_scenario(scenario_root: Path, scenario_name: str) -> tuple[Path, ScenarioConfig]:
    path = _safe_scenario_path(scenario_root, scenario_name)
    kind, diagnostic = _classify_yaml(path)
    if kind != "scenario":
        raise ValueError(
            f"{scenario_name}: не является запускаемым ScenarioConfig / not a runnable ScenarioConfig. "
            f"{diagnostic or ''}"
        )
    return path, load_scenario(path)


def scenario_preview_payload(scenario_root: Path, scenario_name: str) -> dict[str, object]:
    path, scenario = _load_preview_scenario(scenario_root, scenario_name)
    mu_m3_s2 = scenario.force_model.mu_m3_s2
    satellites = []
    for satellite in scenario.constellation.satellites:
        engineering = mean_orbit_engineering_elements(satellite.mean_orbit, mu_m3_s2)
        satellites.append(
            {
                "satellite_id": satellite.satellite_id,
                "plane_id": satellite.plane_id,
                "role": satellite.role,
                "reference_id": satellite.reference_id,
                **engineering,
                "ex": satellite.mean_orbit.ex,
                "ey": satellite.mean_orbit.ey,
                "ix": satellite.mean_orbit.ix,
                "iy": satellite.mean_orbit.iy,
                "initial_mass_kg": satellite.spacecraft.initial_mass_kg,
                "propellant_mass_kg": satellite.spacecraft.propellant_mass_kg,
            }
        )
    return {
        "scenario_name": scenario_name,
        "scenario_id": scenario.scenario_id,
        "authority": _authority_label(scenario),
        "force_mode": scenario.force_model.mode.value,
        "force_model_fingerprint": scenario.force_model.fingerprint(),
        "epoch": scenario.epoch.isoformat(),
        "frame": scenario.frame.value,
        "time_scale": scenario.time_scale.value,
        "duration_s": scenario.duration_s,
        "output_step_s": scenario.output_step_s,
        "predicted_sample_count": predicted_output_sample_count(scenario.duration_s, scenario.output_step_s),
        "duration_presets_s": DURATION_PRESETS_S,
        "satellites": satellites,
        "geometry_preflight": constellation_geometry_preflight(scenario.constellation.satellites, mu_m3_s2),
        "navigation_sites": [site.model_dump(mode="json") for site in scenario.navigation_sites],
        "normalized": scenario.model_dump(mode="json"),
        "yaml_text": path.read_text(encoding="utf-8"),
        "mean_element_rule_ru": (
            "Вековое поведение оценивается по средним элементам, согласованным с используемой моделью сил. "
            "Мгновенная оскулирующая большая полуось не является критерием векового управления."
        ),
        "mean_element_rule_en": (
            "Secular behavior is evaluated from force-model-consistent mean elements; "
            "instantaneous osculating semi-major axis is not a secular control criterion."
        ),
    }


def authority_preflight(scenario: ScenarioConfig, timeout_s: float = 2.0) -> dict[str, object]:
    if scenario.force_model.mode == ForceMode.SCREENING:
        return {
            "ready": True,
            "authority": _authority_label(scenario),
            "reason_ru": "Локальный Screening не требует Orekit sidecar.",
            "reason_en": "Local screening authority does not require the Orekit sidecar.",
        }
    if not scenario.orekit_sidecar_url:
        return {
            "ready": False,
            "authority": _authority_label(scenario),
            "reason_ru": "orekit_sidecar_url не задан.",
            "reason_en": "orekit_sidecar_url is not configured.",
        }
    parsed = urlparse(scenario.orekit_sidecar_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return {
            "ready": False,
            "authority": _authority_label(scenario),
            "reason_ru": "orekit_sidecar_url должен быть явным http(s)-адресом.",
            "reason_en": "orekit_sidecar_url must be an explicit http(s) endpoint.",
        }
    health_url = scenario.orekit_sidecar_url.rstrip("/") + "/healthz"
    try:
        with open_orekit_url(health_url, timeout_s) as response:
            payload: dict[str, Any] = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return {
            "ready": False,
            "authority": _authority_label(scenario),
            "reason_ru": f"Orekit authority недоступен: {exc}",
            "reason_en": f"Orekit authority unavailable: {exc}",
        }
    data_sha = str(payload.get("orekit_data_sha256", ""))
    valid_sha = len(data_sha) == 64
    if valid_sha:
        try:
            int(data_sha, 16)
        except ValueError:
            valid_sha = False
    ready = payload.get("status") == "ok" and payload.get("backend") == "orekit" and valid_sha
    result: dict[str, object] = {
        "ready": ready,
        "authority": _authority_label(scenario),
        "backend": payload.get("backend"),
        "orekit_version": payload.get("orekit_version"),
        "orekit_data_revision": payload.get("orekit_data_revision"),
        "orekit_data_sha256": payload.get("orekit_data_sha256"),
    }
    if not ready:
        result["reason_ru"] = "Ответ Orekit health не содержит полного набора authority metadata."
        result["reason_en"] = "Orekit health response lacks complete authority metadata."
    return result


def _page() -> str:
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>OC GNSS STRUCT CONTROL — Engineering Preview {PREVIEW_VERSION}</title>
<style>
body{{font-family:Segoe UI,Arial,sans-serif;margin:0;background:#f4f6f8;color:#17202a}}header{{background:#17202a;color:white;padding:14px 24px;display:flex;justify-content:space-between;gap:20px}}main{{padding:20px;display:grid;grid-template-columns:340px minmax(0,1fr);gap:18px}}.card{{background:white;border:1px solid #d9dee3;border-radius:8px;padding:16px;margin-bottom:14px}}select,input,button{{width:100%;box-sizing:border-box;padding:9px;margin-top:8px}}button{{cursor:pointer;font-weight:600}}.badge{{display:inline-block;padding:6px 10px;border-radius:6px;background:#eef2f5;font-weight:700}}.table-wrap{{overflow-x:auto}}table{{border-collapse:collapse;width:100%;font-size:13px;white-space:nowrap}}th,td{{border-bottom:1px solid #e5e8eb;padding:7px;text-align:right}}th:first-child,td:first-child{{text-align:left}}pre{{white-space:pre-wrap;word-break:break-word;background:#111820;color:#d9e2ec;padding:12px;border-radius:6px;max-height:360px;overflow:auto}}.status{{padding:9px;border-radius:6px;background:#eef2f5;margin-top:10px}}.danger{{background:#ffe8e8}}.ok{{background:#e8f7ed}}.hint{{font-size:12px;color:#566573}}.geometry-plane{{margin:8px 0;padding:8px;background:#f7f9fa;border-radius:6px}}.oplinks{{display:flex;gap:14px;flex-wrap:wrap;margin-top:10px}}.oplinks a,a.result{{font-weight:700}}@media(max-width:800px){{main{{grid-template-columns:1fr}}header{{flex-direction:column}}}}
</style></head><body>
<header><div><b>OC GNSS STRUCT CONTROL — Engineering Preview {PREVIEW_VERSION}</b><br><small id="subtitle"></small></div><div><button onclick="setLang('ru')">Русский</button><button onclick="setLang('en')">English</button></div></header>
<main><aside>
<div class="card"><b data-i18n="scenario"></b><select id="scenario"></select><label data-i18n="horizon"></label><select id="durationPreset" onchange="renderDuration()"><option value="scenario">Scenario</option><option value="1d">1 d</option><option value="8d">8 d</option><option value="30d">30 d</option><option value="90d">90 d</option><option value="1y">1 y</option><option value="5y">5 y</option><option value="custom">Custom</option></select><input id="customDuration" type="number" min="0" step="1" placeholder="duration, s" oninput="renderDuration()"><div id="durationInfo" class="hint"></div><button id="openBtn" onclick="loadScenario()"></button><button id="runBtn" onclick="runScenario()"></button><div id="status" class="status"></div><a id="result" class="result" target="_blank"></a></div>
<div class="card"><b data-i18n="authority"></b><p id="authority" class="badge">—</p><p id="preflight">—</p><p id="physics"></p></div><div class="card"><b data-i18n="other"></b><div id="other">—</div></div>
</aside><section><div class="card"><h2 id="title"></h2><div id="meta"></div></div><div class="card"><h3 data-i18n="constellation"></h3><p class="hint" data-i18n="engineeringHint"></p><div id="fleet" class="table-wrap"></div></div><div class="card"><h3 data-i18n="geometry"></h3><div id="geometry"></div></div><div class="card"><h3 data-i18n="operations"></h3><p class="hint" data-i18n="operationsHint"></p><div id="operations"></div><div id="oplinks" class="oplinks"></div></div><div class="card"><h3 data-i18n="expert"></h3><pre id="yaml"></pre></div><div class="card"><h3 data-i18n="normalized"></h3><pre id="normalized"></pre></div></section></main>
<script>
const T={{ru:{{subtitle:'Локальная инженерная оболочка. Расчётная authority всегда явна и fail-closed.',scenario:'Сценарий',horizon:'Горизонт расчёта',open:'Открыть сценарий',run:'Запустить выбранный сценарий',ready:'Готово.',loading:'Загрузка…',validated:'Сценарий проверен.',running:'Выполняется расчёт…',completed:'Завершено',report:'Открыть инженерный отчёт',authority:'Расчётная authority',other:'Другие YAML-входы',constellation:'Орбитальная группировка',geometry:'Проверка геометрии ОГ',operations:'Относительная динамика и граница коррекции',operationsHint:'Δu — средняя фаза M+ω, не оскулирующий аргумент широты. Δs — вдольорбитальная оценка a·Δu, не декартово расстояние.',runToSee:'Запустите сценарий, чтобы получить Δu, Δs и прогноз границы.',noOperations:'Нет пар additional/reference.',inside:'В коридоре',outside:'ВНЕ КОРИДОРА',phasePlot:'График Δu и коридора',alongPlot:'График Δs',interactivePhase:'Интерактивный Δu',engineeringHint:'Основной вид использует производные от авторитетных средних эквиноциальных элементов.',expert:'Эксперт / YAML',normalized:'Нормализованный сценарий',select:'Выберите сценарий',none:'Нет',notReady:'НЕ ГОТОВО',isReady:'ГОТОВО',epoch:'Эпоха',frame:'СК / время',duration:'Длительность',step:'шаг',samples:'точек',unchanged:'Fidelity, force model, integrator и output step не меняются.',fingerprint:'Fingerprint модели сил',sat:'КА',plane:'Плоскость',role:'Роль',period:'T, ч',meanA:'Средняя a, км',inclination:'i, °',raan:'Ω, °',phase:'u_mean, °',mass:'Масса, кг',fuel:'Топливо, кг',planes:'Плоскостей',spacecraft:'КА всего',count:'КА',spacing:'Шаг u_mean',raanOffset:'ΔΩ от P1',phaseOffset:'Фаза mod slot',pair:'Пара',deltaU:'Δu, °',driftDay:'дрейф, °/сут',driftYear:'дрейф, °/год',deltaS:'Δs, км',alongRate:'Δv вдоль, м/с',corridor:'±коридор, °',state:'Состояние',boundary:'граница, °',timeBoundary:'до границы, сут',loadFail:'Ошибка загрузки',runFail:'Ошибка расчёта'}},en:{{subtitle:'Local engineering shell. Computation authority is explicit and fail-closed.',scenario:'Scenario',horizon:'Propagation horizon',open:'Open scenario',run:'Run selected scenario',ready:'Ready.',loading:'Loading…',validated:'Scenario validated.',running:'Running scenario…',completed:'Completed',report:'Open engineering report',authority:'Authority',other:'Other YAML inputs',constellation:'Constellation',geometry:'Constellation geometry preflight',operations:'Relative operations and correction boundary',operationsHint:'Δu is mean phase M+ω, not osculating argument of latitude. Δs is along-track arc proxy a·Δu, not Cartesian separation.',runToSee:'Run the scenario to obtain Δu, Δs and boundary forecast.',noOperations:'No additional/reference pairs.',inside:'Inside corridor',outside:'OUTSIDE CORRIDOR',phasePlot:'Δu and corridor plot',alongPlot:'Δs plot',interactivePhase:'Interactive Δu',engineeringHint:'Primary view uses quantities derived from authoritative mean equinoctial elements.',expert:'Expert / YAML',normalized:'Normalized scenario',select:'Select a scenario',none:'None',notReady:'NOT READY',isReady:'READY',epoch:'Epoch',frame:'Frame / time',duration:'Duration',step:'step',samples:'samples',unchanged:'Fidelity, force model, integrator and output step remain unchanged.',fingerprint:'Force fingerprint',sat:'Satellite',plane:'Plane',role:'Role',period:'T, h',meanA:'Mean a, km',inclination:'i, deg',raan:'Ω, deg',phase:'u_mean, deg',mass:'Mass, kg',fuel:'Fuel, kg',planes:'Planes',spacecraft:'Spacecraft',count:'Count',spacing:'u_mean spacing',raanOffset:'ΔΩ from P1',phaseOffset:'Phase mod slot',pair:'Pair',deltaU:'Δu, deg',driftDay:'drift, deg/day',driftYear:'drift, deg/year',deltaS:'Δs, km',alongRate:'along-track Δv, m/s',corridor:'±corridor, deg',state:'State',boundary:'boundary, deg',timeBoundary:'to boundary, days',loadFail:'Load failed',runFail:'Run failed'}}}};
let lang=localStorage.getItem('preview-lang')||'ru',current=null,catalog=null,preflight=null,operations=null,artifactLinks=null;
const esc=v=>String(v).replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));const tr=k=>T[lang][k]||k;const fmt=(v,n=3)=>v===null||v===undefined?'—':Number(v).toFixed(n);
function setStatus(t,k=''){{const e=document.getElementById('status');e.textContent=t;e.className='status '+k}}function setLang(v){{lang=v;localStorage.setItem('preview-lang',v);document.documentElement.lang=v;renderLanguage()}}
function renderLanguage(){{document.getElementById('subtitle').textContent=tr('subtitle');document.querySelectorAll('[data-i18n]').forEach(e=>e.textContent=tr(e.dataset.i18n));openBtn.textContent=tr('open');runBtn.textContent=tr('run');renderOther();renderCurrent();renderOperations();renderDuration()}}
function renderOther(){{if(!catalog)return;other.innerHTML=catalog.other_inputs.length?catalog.other_inputs.map(x=>`<div><b>${{esc(x.name)}}</b><br><small>${{esc(x.kind)}} — ${{esc(x.diagnostic)}}</small></div>`).join('<hr>'):tr('none')}}
function authorityText(mode){{if(lang==='ru')return mode==='screening'?'SCREENING — аналитическая authority средних элементов':mode==='design'?'DESIGN — требуется Orekit DSST authority':'VALIDATION — требуется численная Orekit authority';return current?current.authority:'—'}}
function selectedDuration(){{if(!current)return null;const p=durationPreset.value;if(p==='scenario')return Number(current.duration_s);if(p==='custom')return Number(customDuration.value);return Number(current.duration_presets_s[p])}}
function renderDuration(){{if(!current)return;const custom=durationPreset.value==='custom';customDuration.disabled=!custom;const d=selectedDuration();const valid=Number.isFinite(d)&&d>0;const samples=valid?Math.ceil(d/Number(current.output_step_s))+1:'—';durationInfo.textContent=(valid?`${{tr('duration')}}: ${{d}} s; ${{tr('step')}}: ${{current.output_step_s}} s; ${{tr('samples')}}: ${{samples}}. `:'')+tr('unchanged')}}
function renderFleet(rows){{let h=`<table><tr><th>${{tr('sat')}}</th><th>${{tr('plane')}}</th><th>${{tr('role')}}</th><th>${{tr('period')}}</th><th>${{tr('meanA')}}</th><th>${{tr('inclination')}}</th><th>${{tr('raan')}}</th><th>${{tr('phase')}}</th><th>${{tr('mass')}}</th><th>${{tr('fuel')}}</th></tr>`;for(const x of rows)h+=`<tr><td>${{esc(x.satellite_id)}}</td><td>${{esc(x.plane_id)}}</td><td>${{esc(x.role)}}</td><td>${{fmt(x.period_h,4)}}</td><td>${{fmt(x.a_mean_km,3)}}</td><td>${{fmt(x.inclination_deg,4)}}</td><td>${{fmt(x.raan_deg,4)}}</td><td>${{fmt(x.u_mean_deg,4)}}</td><td>${{fmt(x.initial_mass_kg,2)}}</td><td>${{fmt(x.propellant_mass_kg,2)}}</td></tr>`;return h+'</table>'}}
function renderGeometry(g){{if(!g)return '—';let h=`<p><b>${{tr('planes')}}:</b> ${{g.plane_count}} &nbsp; <b>${{tr('spacecraft')}}:</b> ${{g.satellite_count}}</p>`;for(const p of g.planes)h+=`<div class="geometry-plane"><b>${{esc(p.plane_id)}}</b>: ${{tr('count')}}=${{p.satellite_count}}, Ω=${{fmt(p.raan_mean_deg,4)}}°, i=${{fmt(p.inclination_mean_deg,4)}}°, ${{tr('spacing')}}=${{fmt(p.in_plane_spacing_mean_deg,4)}}°</div>`;if(g.interplane.length){{h+='<div class="table-wrap"><table><tr><th>'+tr('plane')+'</th><th>'+tr('raanOffset')+'</th><th>'+tr('phaseOffset')+'</th></tr>';for(const x of g.interplane)h+=`<tr><td>${{esc(x.plane_id)}}</td><td>${{fmt(x.raan_offset_deg,4)}}°</td><td>${{fmt(x.phase_offset_mod_slot_deg,4)}}°</td></tr>`;h+='</table></div>'}}return h+`<p class="hint">${{esc(lang==='ru'?g.semantics_ru:g.semantics_en)}}</p>`}}
function renderOperations(){{if(!operations){{operationsEl().innerHTML=`<p class="hint">${{tr('runToSee')}}</p>`;oplinks.innerHTML='';return}}if(!operations.available){{operationsEl().innerHTML=`<p>${{tr('noOperations')}}</p>`;oplinks.innerHTML='';return}}let h=`<div class="table-wrap"><table><tr><th>${{tr('pair')}}</th><th>${{tr('deltaU')}}</th><th>${{tr('driftDay')}}</th><th>${{tr('driftYear')}}</th><th>${{tr('deltaS')}}</th><th>${{tr('alongRate')}}</th><th>${{tr('corridor')}}</th><th>${{tr('state')}}</th><th>${{tr('boundary')}}</th><th>${{tr('timeBoundary')}}</th></tr>`;for(const x of operations.pairs){{h+=`<tr><td>${{esc(x.pair_id)}}</td><td>${{fmt(x.final_delta_u_deg,4)}}</td><td>${{fmt(x.drift_deg_day,6)}}</td><td>${{fmt(x.drift_deg_julian_year,4)}}</td><td>${{fmt(x.final_along_track_proxy_km,3)}}</td><td>${{fmt(x.along_track_proxy_rate_m_s,6)}}</td><td>${{fmt(x.corridor_half_width_deg,4)}}</td><td><b>${{x.inside_corridor?tr('inside'):tr('outside')}}</b></td><td>${{fmt(x.predicted_boundary_deg,4)}}</td><td>${{fmt(x.time_to_boundary_days,3)}}</td></tr>`}}h+='</table></div>';operationsEl().innerHTML=h;if(artifactLinks)oplinks.innerHTML=`<a target="_blank" href="${{artifactLinks.phase_plot}}">${{tr('phasePlot')}}</a><a target="_blank" href="${{artifactLinks.along_track_plot}}">${{tr('alongPlot')}}</a><a target="_blank" href="${{artifactLinks.interactive_phase}}">${{tr('interactivePhase')}}</a>`}}
function operationsEl(){{return document.getElementById('operations')}}
function renderCurrent(){{if(!current)return;title.textContent=current.scenario_id;authority.textContent=authorityText(current.force_mode);physics.textContent=lang==='ru'?current.mean_element_rule_ru:current.mean_element_rule_en;meta.innerHTML=`${{tr('epoch')}}: ${{esc(current.epoch)}}<br>${{tr('frame')}}: ${{esc(current.frame)}} / ${{esc(current.time_scale)}}<br>${{tr('duration')}}: ${{current.duration_s}} s; ${{tr('step')}}: ${{current.output_step_s}} s; ${{tr('samples')}}: ${{current.predicted_sample_count}}<br>${{tr('fingerprint')}}: <code>${{esc(current.force_model_fingerprint)}}</code>`;fleet.innerHTML=renderFleet(current.satellites);geometry.innerHTML=renderGeometry(current.geometry_preflight);yaml.textContent=current.yaml_text;normalized.textContent=JSON.stringify(current.normalized,null,2);renderPreflight();renderDuration()}}
function renderPreflight(){{if(!preflight)return;const reason=lang==='ru'?preflight.reason_ru:preflight.reason_en;document.getElementById('preflight').textContent=preflight.ready?tr('isReady')+': '+(preflight.orekit_version?`Orekit ${{preflight.orekit_version}}`:reason||''):tr('notReady')+': '+(reason||'authority metadata incomplete')}}
async function bootstrap(){{const r=await fetch('/api/scenarios');catalog=await r.json();scenario.replaceChildren(...catalog.scenarios.map(x=>{{const o=document.createElement('option');o.value=x;o.textContent=x;return o}}));renderLanguage();setStatus(tr('ready'));if(catalog.scenarios.length)await loadScenario()}}
async function loadScenario(){{const n=scenario.value;if(!n)return;setStatus(tr('loading'));result.textContent='';operations=null;artifactLinks=null;renderOperations();const r=await fetch('/api/scenarios/'+encodeURIComponent(n));const d=await r.json();if(!r.ok){{setStatus(d.detail||tr('loadFail'),'danger');return}}current=d;durationPreset.value='scenario';customDuration.value='';const p=await fetch('/api/preflight/'+encodeURIComponent(n));preflight=await p.json();renderCurrent();setStatus(tr('validated'),'ok')}}
async function runScenario(){{const n=scenario.value;if(!n)return;const p=durationPreset.value;const custom=p==='custom'?Number(customDuration.value):null;setStatus(tr('running'));const r=await fetch('/api/runs',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{scenario_name:n,duration_preset:p,custom_duration_s:custom}})}});const d=await r.json();if(!r.ok){{setStatus(d.detail||tr('runFail'),'danger');return}}operations=d.operations;artifactLinks=d.artifacts;renderOperations();durationInfo.textContent=`${{tr('duration')}}: ${{d.duration.duration_s}} s; ${{tr('step')}}: ${{d.duration.output_step_s}} s; ${{tr('samples')}}: ${{d.duration.predicted_sample_count}}. `+tr('unchanged');setStatus(tr('completed')+': '+d.run_dir,'ok');result.href=d.report_url;result.textContent=tr('report')}}
bootstrap().catch(e=>setStatus(String(e),'danger'));
</script></body></html>"""


def create_preview_app(scenario_root: Path = Path("scenarios"), output_root: Path = Path("runs")) -> FastAPI:
    app = FastAPI(title="OC GNSS STRUCT CONTROL Engineering Preview", version=PREVIEW_VERSION)

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        return HTMLResponse(_page())

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "preview": PREVIEW_VERSION}

    @app.get("/api/scenarios")
    def scenarios() -> dict[str, object]:
        return preview_catalog(scenario_root)

    @app.get("/api/scenarios/{scenario_name}")
    def scenario(scenario_name: str) -> dict[str, object]:
        try:
            return scenario_preview_payload(scenario_root, scenario_name)
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/preflight/{scenario_name}")
    def preflight(scenario_name: str) -> dict[str, object]:
        try:
            _, loaded = _load_preview_scenario(scenario_root, scenario_name)
            return authority_preflight(loaded)
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/runs")
    def run(request: PreviewRunRequest) -> dict[str, object]:
        try:
            scenario_path, _ = _load_preview_scenario(scenario_root, request.scenario_name)
            execution = run_scenario_with_duration(
                scenario_path,
                output_root,
                preset=request.duration_preset,
                custom_duration_s=request.custom_duration_s,
            )
            run_dir = execution.run_dir
            relative = run_dir.resolve().relative_to(output_root.resolve())
            if len(relative.parts) != 2:
                raise RuntimeError("Неожиданная структура каталога запуска / unexpected run directory layout")
            operations = preview_operations_payload(run_dir)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        scenario_id, run_id = relative.parts
        prefix = f"/api/results/{scenario_id}/{run_id}"
        return {
            "run_dir": str(run_dir),
            "report_url": f"{prefix}/report.html",
            "operations": operations,
            "duration": {
                "preset": execution.preset,
                "duration_s": execution.duration_s,
                "output_step_s": execution.output_step_s,
                "predicted_sample_count": execution.predicted_sample_count,
            },
            "artifacts": {
                "phase_plot": f"{prefix}/11_delta_u_mean.png",
                "along_track_plot": f"{prefix}/12_along_track_mean_arc_proxy.png",
                "interactive_phase": f"{prefix}/interactive_delta_u_mean.html",
            },
        }

    @app.get("/api/results/{scenario_id}/{run_id}/report.html", response_class=FileResponse)
    def report(scenario_id: str, run_id: str) -> FileResponse:
        try:
            report_path = _safe_result_file(output_root, scenario_id, run_id, "report.html")
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return FileResponse(report_path, media_type="text/html")

    @app.get("/api/results/{scenario_id}/{run_id}/{name}", response_class=FileResponse)
    def result_artifact(scenario_id: str, run_id: str, name: str) -> FileResponse:
        if name not in _RESULT_ARTIFACTS:
            raise HTTPException(status_code=404, detail="Result artifact is not exposed by Preview")
        try:
            path = _safe_result_file(output_root, scenario_id, run_id, name)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        media_type = "image/png" if name.endswith(".png") else "text/html"
        return FileResponse(path, media_type=media_type)

    return app


app = create_preview_app()


def render_preview_page_for_test() -> str:
    return _page()
