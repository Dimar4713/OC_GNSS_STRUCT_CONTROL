# OC GNSS STRUCT CONTROL — Engineering Preview Python 0.1.5

## Русский

### Назначение
Engineering Preview 0.1.5 — экспертная Windows-версия для проверки сценариев, физической постановки, расчётной authority, геометрии ОГ, относительной динамики, длительных горизонтов, воспроизводимых P2 closed-loop операций и запуска принятых Design/Robustness workflows.

### Возможности 0.1.5
- инженерный контур: `T`, `a`, `i`, `Ω`, `u_mean`, Geometry Preflight, `Δu`, `Δs`, скорости дрейфа, фазовый коридор, время до границы и горизонты 1 d…5 y/custom;
- отдельный блок **Замкнутый контур управления / Closed-loop control** с P2 политиками `NO CONTROL`, `RETURN-TO-CENTER`, `BOUNDARY-TO-BOUNDARY`;
- никаких скрытых control defaults: campaign/coast horizons, authority grid/windows, RTN impulse limits, MIB, trust tolerances, target ROE и MPC weights задаются оператором в явном control-profile JSON;
- correction-capable политики требуют `VALIDATION` и численную Orekit authority; `NO CONTROL` не вызывает maneuver authority;
- отдельный блок **Design / Robustness workflows — Проектирование / Робастность** запускает существующие application runners без второго optimizer/propagator/Monte Carlo слоя;
- Design требует три явных входа: Screening ScenarioConfig, Validation ScenarioConfig и `design_pipeline_config`;
- Robustness требует Validation ScenarioConfig и `robustness_campaign_config`;
- список pipeline/campaign конфигураций строится только из классифицированных `other_inputs`; неверный YAML-kind отклоняется до backend execution;
- UI показывает ссылки на уже существующие authoritative Design/Robustness artifacts, не пересчитывая рекомендацию или статистику самостоятельно.

### Физическая семантика
`u_mean = λ - Ω = M + ω` — средняя фазовая координата, не оскулирующий аргумент широты.

`Δu` — разность средних фаз дополнительного и опорного КА. Она не тождественна D'Amico `delta_lambda`.

`Δs ≈ a_ref·Δu` — инженерная оценка средней вдольорбитальной дуги, а не декартово физическое расстояние.

Фазовый коридор остаётся жёстким operator `Δu` constraint. Screening evidence никогда не разрешает манёвр и не заменяет numerical validation.

### Быстрый запуск Windows 10
1. Установите Python 3.12 для текущего пользователя, если он отсутствует.
2. Распакуйте ZIP и запустите `start-preview.bat`.
3. Launcher создаст локальную `.venv-preview`; не копируйте готовую `.venv-preview` между компьютерами.
4. Для DESIGN/VALIDATION требуется Java 17+ и включённый в bundle проверенный Orekit runtime/data.
5. Выберите сценарий и проверьте **Расчётную authority** и **Проверку геометрии ОГ**.
6. Для propagation-диагностики используйте обычный scenario run и горизонты.
7. Для P2 операций используйте **Замкнутый контур управления** и полный явный control-profile JSON.
8. Для Design выберите screening scenario, validation scenario и Design pipeline config, затем нажмите **Run Design**.
9. Для Robustness выберите validation scenario и Robustness campaign config, затем нажмите **Run Robustness**.
10. После выполнения открывайте штатные report/manifest/recommendation/summary artifacts по ссылкам Preview.

### Fidelity
- **SCREENING** — Python analytical/synthetic mean-element authority.
- **DESIGN** — screening search/DSST design evidence, но финальная рекомендация Design pipeline требует Orekit Numerical replay.
- **VALIDATION** — Orekit Numerical authority.
- **ROBUSTNESS** — существующий Orekit Numerical robustness campaign с явным uncertainty/authority contract.

High-fidelity режимы fail-closed; silent fallback запрещён. Preview только маршрутизирует явные inputs в принятые application runners.

Preview привязан к localhost. Результаты UI сохраняются в `preview/results/`.

---

## English

### Purpose
Engineering Preview 0.1.5 is an expert-facing Windows build for scenario/physics validation, explicit computation authority, constellation geometry, relative operations, long horizons, reproducible P2 closed-loop operations, and direct launch of the accepted Design/Robustness workflows.

### Capabilities in 0.1.5
- engineering surface: `T`, `a`, `i`, `Ω`, `u_mean`, Geometry Preflight, `Δu`, `Δs`, drift rates, phase corridor, time-to-boundary and explicit 1 d…5 y/custom horizons;
- separate **Closed-loop control / Замкнутый контур управления** section for P2 `NO CONTROL`, `RETURN-TO-CENTER`, `BOUNDARY-TO-BOUNDARY`;
- no hidden control defaults: campaign/coast horizons, authority grid/windows, RTN impulse limits, MIB, trust tolerances, target ROE and MPC weights are operator-supplied in explicit control-profile JSON;
- correction-capable policies require `VALIDATION` and numerical Orekit authority; `NO CONTROL` invokes no maneuver authority;
- separate **Design / Robustness workflows — Проектирование / Робастность** section routes directly to the existing application runners with no second optimizer, propagator, or Monte Carlo implementation;
- Design requires three explicit inputs: Screening ScenarioConfig, Validation ScenarioConfig, and a `design_pipeline_config`;
- Robustness requires a Validation ScenarioConfig and `robustness_campaign_config`;
- pipeline/campaign selectors are populated only from classified `other_inputs`; a wrong YAML kind is rejected before backend execution;
- the UI exposes links to existing authoritative Design/Robustness artifacts and does not recompute recommendations or statistics.

### Physics semantics
`u_mean = λ - Ω = M + ω` is a mean phase coordinate, not osculating argument of latitude.

`Δu` is the additional/reference mean-phase difference and remains distinct from D'Amico `delta_lambda`.

`Δs ≈ a_ref·Δu` is a mean along-track arc engineering proxy, not Cartesian physical separation.

The phase corridor remains a hard operator `Δu` constraint. Screening evidence can never authorize a maneuver or replace numerical validation.

### Windows 10 quick start
1. Install Python 3.12 for the current user if needed.
2. Extract the ZIP and run `start-preview.bat`.
3. Let the launcher create `.venv-preview`; do not copy a prepared virtual environment between PCs.
4. DESIGN/VALIDATION require Java 17+ and the verified bundled Orekit runtime/data.
5. Select a scenario and inspect **Authority** and **Constellation Geometry Preflight**.
6. Use normal scenario run/horizon controls for propagation diagnostics.
7. Use **Closed-loop control** plus a complete explicit control-profile JSON for P2 operations.
8. For Design select the screening scenario, validation scenario and Design pipeline config, then choose **Run Design**.
9. For Robustness select the validation scenario and Robustness campaign config, then choose **Run Robustness**.
10. Open the standard report/manifest/recommendation/summary artifacts from the Preview links.

### Fidelity
- **SCREENING** — Python analytical/synthetic mean-element authority.
- **DESIGN** — screening search/DSST design evidence; final Design-pipeline recommendation requires Orekit Numerical replay.
- **VALIDATION** — Orekit Numerical authority.
- **ROBUSTNESS** — existing Orekit Numerical robustness campaign with explicit uncertainty/authority contract.

High-fidelity execution remains fail-closed; silent fallback is forbidden. Preview only routes explicit inputs to the accepted application runners.

The Preview binds to localhost. UI run evidence is stored under `preview/results/`.
