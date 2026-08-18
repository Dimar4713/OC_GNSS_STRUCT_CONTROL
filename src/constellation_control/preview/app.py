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
from constellation_control.application.run import load_scenario, run_scenario
from constellation_control.domain.models import ForceMode, ScenarioConfig

PREVIEW_VERSION = "0.1.1"


class PreviewRunRequest(BaseModel):
    scenario_name: str


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
    scenarios = preview_catalog(scenario_root)["scenarios"]
    return list(cast(list[str], scenarios))


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
    satellites = [
        {
            "satellite_id": satellite.satellite_id,
            "plane_id": satellite.plane_id,
            "role": satellite.role,
            "reference_id": satellite.reference_id,
            "a_mean_m": satellite.mean_orbit.a_m,
            "ex": satellite.mean_orbit.ex,
            "ey": satellite.mean_orbit.ey,
            "ix": satellite.mean_orbit.ix,
            "iy": satellite.mean_orbit.iy,
            "lambda_rad": satellite.mean_orbit.lambda_rad,
            "initial_mass_kg": satellite.spacecraft.initial_mass_kg,
            "propellant_mass_kg": satellite.spacecraft.propellant_mass_kg,
        }
        for satellite in scenario.constellation.satellites
    ]
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
        "satellites": satellites,
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
body{{font-family:Segoe UI,Arial,sans-serif;margin:0;background:#f4f6f8;color:#17202a}}
header{{background:#17202a;color:white;padding:14px 24px;display:flex;justify-content:space-between;gap:20px;align-items:center}}
header small{{opacity:.78}} .lang{{display:flex;gap:6px}} .lang button{{width:auto;margin:0;padding:7px 12px}}
main{{padding:20px;display:grid;grid-template-columns:320px 1fr;gap:18px}} .card{{background:white;border:1px solid #d9dee3;border-radius:8px;padding:16px;margin-bottom:14px}}
select,button{{width:100%;padding:9px;margin-top:8px}} button{{cursor:pointer;font-weight:600}} .badge{{display:inline-block;padding:6px 10px;border-radius:6px;background:#eef2f5;font-weight:700}}
table{{border-collapse:collapse;width:100%;font-size:13px}} th,td{{border-bottom:1px solid #e5e8eb;padding:7px;text-align:right}} th:first-child,td:first-child{{text-align:left}}
pre{{white-space:pre-wrap;word-break:break-word;background:#111820;color:#d9e2ec;padding:12px;border-radius:6px;max-height:360px;overflow:auto}} .status{{padding:9px;border-radius:6px;background:#eef2f5;margin-top:10px}} .danger{{background:#ffe8e8}} .ok{{background:#e8f7ed}} a.result{{display:block;margin-top:10px;font-weight:700}}
@media(max-width:800px){{main{{grid-template-columns:1fr}} header{{align-items:flex-start;flex-direction:column}}}}
</style></head>
<body>
<header><div><b>OC GNSS STRUCT CONTROL — Engineering Preview {PREVIEW_VERSION}</b><br><small id="subtitle"></small></div><div class="lang"><button onclick="setLang('ru')">Русский</button><button onclick="setLang('en')">English</button></div></header>
<main><aside>
<div class="card"><b data-i18n="scenario"></b><select id="scenario"></select><button id="openBtn" onclick="loadScenario()"></button><button id="runBtn" onclick="runScenario()"></button><div id="status" class="status"></div><a id="result" class="result" target="_blank"></a></div>
<div class="card"><b data-i18n="authority"></b><p id="authority" class="badge">—</p><p id="preflight">—</p><p id="physics"></p></div>
<div class="card"><b data-i18n="other"></b><div id="other">—</div></div>
</aside><section>
<div class="card"><h2 id="title"></h2><div id="meta"></div></div>
<div class="card"><h3 data-i18n="constellation"></h3><div id="fleet"></div></div>
<div class="card"><h3 data-i18n="expert"></h3><pre id="yaml"></pre></div>
<div class="card"><h3 data-i18n="normalized"></h3><pre id="normalized"></pre></div>
</section></main>
<script>
const T={{
ru:{{subtitle:'Локальная инженерная оболочка. Уровень физической достоверности всегда показан явно и работает fail-closed.',scenario:'Сценарий',open:'Открыть сценарий',run:'Запустить выбранный сценарий',ready:'Готово.',loading:'Загрузка…',validated:'Сценарий проверен.',running:'Выполняется расчёт…',completed:'Завершено',report:'Открыть инженерный отчёт',authority:'Расчётная authority',other:'Другие YAML-входы',constellation:'Орбитальная группировка',expert:'Эксперт / YAML',normalized:'Нормализованный сценарий',select:'Выберите сценарий',none:'Нет',notReady:'НЕ ГОТОВО',isReady:'ГОТОВО',epoch:'Эпоха',frame:'СК / время',duration:'Длительность',step:'шаг',fingerprint:'Fingerprint модели сил',sat:'КА',plane:'Плоскость',role:'Роль',meanA:'Средняя a, м',mass:'Масса, кг',fuel:'Топливо, кг',loadFail:'Ошибка загрузки',runFail:'Ошибка расчёта'}},
en:{{subtitle:'Local engineering shell. Physics authority remains explicit and fail-closed.',scenario:'Scenario',open:'Open scenario',run:'Run selected scenario',ready:'Ready.',loading:'Loading…',validated:'Scenario validated.',running:'Running scenario…',completed:'Completed',report:'Open engineering report',authority:'Authority',other:'Other YAML inputs',constellation:'Constellation',expert:'Expert / YAML',normalized:'Normalized scenario',select:'Select a scenario',none:'None',notReady:'NOT READY',isReady:'READY',epoch:'Epoch',frame:'Frame / time',duration:'Duration',step:'step',fingerprint:'Force fingerprint',sat:'Satellite',plane:'Plane',role:'Role',meanA:'Mean a, m',mass:'Mass, kg',fuel:'Fuel, kg',loadFail:'Load failed',runFail:'Run failed'}}
}};
let lang=localStorage.getItem('preview-lang')||'ru'; let current=null; let catalog=null; let preflight=null;
const esc=v=>String(v).replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c])); const tr=k=>T[lang][k]||k;
function setStatus(t,k=''){{const e=document.getElementById('status');e.textContent=t;e.className='status '+k}}
function setLang(v){{lang=v;localStorage.setItem('preview-lang',v);document.documentElement.lang=v;renderLanguage();}}
function renderLanguage(){{document.getElementById('subtitle').textContent=tr('subtitle');document.querySelectorAll('[data-i18n]').forEach(e=>e.textContent=tr(e.dataset.i18n));document.getElementById('openBtn').textContent=tr('open');document.getElementById('runBtn').textContent=tr('run');if(!current)document.getElementById('title').textContent=tr('select');renderOther();renderCurrent();}}
function renderOther(){{if(!catalog)return;document.getElementById('other').innerHTML=catalog.other_inputs.length?catalog.other_inputs.map(x=>`<div><b>${{esc(x.name)}}</b><br><small>${{esc(x.kind)}} — ${{esc(x.diagnostic)}}</small></div>`).join('<hr>'):tr('none')}}
function authorityText(mode){{if(lang==='ru')return mode==='screening'?'SCREENING — аналитическая authority средних элементов':mode==='design'?'DESIGN — требуется Orekit DSST authority':'VALIDATION — требуется численная Orekit authority';return current?current.authority:'—'}}
function renderFleet(rows){{let h=`<table><tr><th>${{tr('sat')}}</th><th>${{tr('plane')}}</th><th>${{tr('role')}}</th><th>${{tr('meanA')}}</th><th>λ, rad</th><th>${{tr('mass')}}</th><th>${{tr('fuel')}}</th></tr>`;for(const x of rows)h+=`<tr><td>${{esc(x.satellite_id)}}</td><td>${{esc(x.plane_id)}}</td><td>${{esc(x.role)}}</td><td>${{esc(x.a_mean_m)}}</td><td>${{esc(x.lambda_rad)}}</td><td>${{esc(x.initial_mass_kg)}}</td><td>${{esc(x.propellant_mass_kg)}}</td></tr>`;return h+'</table>'}}
function renderCurrent(){{if(!current)return;document.getElementById('title').textContent=current.scenario_id;document.getElementById('authority').textContent=authorityText(current.force_mode);document.getElementById('physics').textContent=lang==='ru'?current.mean_element_rule_ru:current.mean_element_rule_en;document.getElementById('meta').innerHTML=`${{tr('epoch')}}: ${{esc(current.epoch)}}<br>${{tr('frame')}}: ${{esc(current.frame)}} / ${{esc(current.time_scale)}}<br>${{tr('duration')}}: ${{esc(current.duration_s)}} s; ${{tr('step')}}: ${{esc(current.output_step_s)}} s<br>${{tr('fingerprint')}}: <code>${{esc(current.force_model_fingerprint)}}</code>`;document.getElementById('fleet').innerHTML=renderFleet(current.satellites);document.getElementById('yaml').textContent=current.yaml_text;document.getElementById('normalized').textContent=JSON.stringify(current.normalized,null,2);renderPreflight();}}
function renderPreflight(){{if(!preflight)return;const e=document.getElementById('preflight');const reason=lang==='ru'?preflight.reason_ru:preflight.reason_en;e.textContent=preflight.ready?tr('isReady')+': '+(preflight.orekit_version?`Orekit ${{preflight.orekit_version}}`:reason||''):tr('notReady')+': '+(reason||'authority metadata incomplete');e.className=preflight.ready?'ok':'danger'}}
async function bootstrap(){{const r=await fetch('/api/scenarios');catalog=await r.json();const s=document.getElementById('scenario');s.replaceChildren(...catalog.scenarios.map(x=>{{const o=document.createElement('option');o.value=x;o.textContent=x;return o}}));renderLanguage();setStatus(tr('ready'));if(catalog.scenarios.length)await loadScenario()}}
async function loadScenario(){{const n=document.getElementById('scenario').value;if(!n)return;setStatus(tr('loading'));document.getElementById('result').textContent='';const r=await fetch('/api/scenarios/'+encodeURIComponent(n));const d=await r.json();if(!r.ok){{setStatus(d.detail||tr('loadFail'),'danger');return}}current=d;const p=await fetch('/api/preflight/'+encodeURIComponent(n));preflight=await p.json();renderCurrent();setStatus(tr('validated'),'ok')}}
async function runScenario(){{const n=document.getElementById('scenario').value;if(!n)return;setStatus(tr('running'));const r=await fetch('/api/runs',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{scenario_name:n}})}});const d=await r.json();if(!r.ok){{setStatus(d.detail||tr('runFail'),'danger');return}}setStatus(tr('completed')+': '+d.run_dir,'ok');const a=document.getElementById('result');a.href=d.report_url;a.textContent=tr('report')}}
bootstrap().catch(e=>setStatus(String(e),'danger'));
</script></body></html>"""


def create_preview_app(
    scenario_root: Path = Path("scenarios"),
    output_root: Path = Path("runs"),
) -> FastAPI:
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
    def run(request: PreviewRunRequest) -> dict[str, str]:
        try:
            scenario_path, _ = _load_preview_scenario(scenario_root, request.scenario_name)
            run_dir = run_scenario(scenario_path, output_root)
            relative = run_dir.resolve().relative_to(output_root.resolve())
            if len(relative.parts) != 2:
                raise RuntimeError("Неожиданная структура каталога запуска / unexpected run directory layout")
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        scenario_id, run_id = relative.parts
        return {"run_dir": str(run_dir), "report_url": f"/api/results/{scenario_id}/{run_id}/report.html"}

    @app.get("/api/results/{scenario_id}/{run_id}/report.html", response_class=FileResponse)
    def report(scenario_id: str, run_id: str) -> FileResponse:
        try:
            report_path = _safe_result_file(output_root, scenario_id, run_id, "report.html")
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return FileResponse(report_path, media_type="text/html")

    return app


app = create_preview_app()


def render_preview_page_for_test() -> str:
    return _page()
