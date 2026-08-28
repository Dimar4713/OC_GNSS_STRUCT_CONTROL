# OC GNSS STRUCT CONTROL — Engineering Preview Python 0.2.2
# Руководство пользователя / User Guide

## Русский

### 1. Запуск
1. Распакуйте `engineering-preview-python-0.2.2-win10.zip` в локальный каталог Windows 10/11.
2. Убедитесь, что установлен Python 3.12. Не переносите `.venv-preview` между компьютерами.
3. Запустите `start-preview.bat`.
4. Bootstrap создаст локальное окружение и запустит bundled Java/Orekit 13.1.7.
5. Проверьте `/health`: должно быть `preview = 0.2.2`.

### 2. Authority
Перед расчётом смотрите SCREENING / DESIGN / VALIDATION banner.
- SCREENING — аналитический/synthetic контур; не operational authority.
- DESIGN — Orekit DSST design/screening evidence.
- VALIDATION — Orekit numerical authority.
- DESIGN/VALIDATION fail-closed; недоступный Orekit не заменяется Screening.

### 3. Открытие и редактирование ScenarioConfig
После выбора сценария Preview показывает инженерные параметры, исходный YAML и normalized ScenarioConfig.

В 0.2.2 добавлен рабочий блок **Редактор сценария / Scenario editor**.

Порядок работы:
1. Откройте исходный сценарий.
2. В редакторе измените нужные поля YAML. Разрешено менять полный `ScenarioConfig`, включая:
   - `scenario_id`, epoch/frame/time scale;
   - `duration_s`, `output_step_s`;
   - `force_model` и его параметры;
   - `integrator`;
   - `constraints`;
   - `monte_carlo`;
   - `constellation.satellites`, mean orbit и spacecraft parameters;
   - `maneuvers` и navigation sites.
3. Нажмите **Проверить YAML / Validate YAML**.
4. Preview выполняет полную Pydantic `ScenarioConfig` validation и показывает новый force-model fingerprint.
5. Введите **новое** имя `.yaml/.yml`.
6. Нажмите **Сохранить и открыть / Save and open**.
7. Новый сценарий сразу появляется в каталоге и может использоваться обычным run, closed-loop, Design/Robustness или Optimal Operations при соблюдении их входных контрактов.

Существующий YAML перезаписать нельзя. Это защищает эталонные сценарии и обеспечивает воспроизводимость.

### 4. Геометрия и P1 relative operations
Основной вид показывает `T`, mean `a`, `i`, `Ω`, `u_mean = λ - Ω = M + ω`, Geometry Preflight, `Δu`, drift, `Δs ≈ a_ref·Δu`, proxy velocity, corridor state и boundary forecast.

`u_mean` — средняя фазовая координата, не оскулирующий аргумент широты. `Δu` не равна D'Amico `delta_lambda`. `Δs` — вдольорбитальная инженерная дуговая оценка, не Cartesian distance.

### 5. Propagation horizon
Быстрые пресеты Scenario / 1 d / 8 d / 30 d / 90 d / 1 y / 5 y / Custom меняют только effective `duration_s`. Если нужно изменить `output_step_s`, integrator или force model, используйте Scenario editor и сохраните новый YAML.

### 6. Closed-loop control P2
Поддерживаются `NO CONTROL`, `RETURN-TO-CENTER`, `BOUNDARY-TO-BOUNDARY`.

Все управляющие числа задаются явно через control profile JSON: campaign/coast horizons, grids/windows, RTN impulse limits, MIB, trust tolerances, target ROE и MPC weights. Correction-capable policies требуют VALIDATION + Orekit numerical authority.

Accepted P2 chain включает repeated campaign, resource ledger, ΔV/fuel/lifetime evidence, checkpoint/resume и safe-stop. UI показывает persisted evidence и не пересчитывает authority сам.

### 7. Design workflow
Выберите явные:
1. Screening ScenarioConfig;
2. Validation ScenarioConfig;
3. `design_pipeline_config`.

Preview вызывает существующий `run_design_application()` и показывает его artifacts. Собственного optimizer/propagator в UI нет.

### 8. Robustness workflow
Выберите Validation ScenarioConfig и `robustness_campaign_config`. Preview вызывает существующий numerical Orekit robustness application. Sampling/statistics/violation evidence не пересчитывается в UI.

### 9. Optimal Operations 0.2
Рабочий поток двухэтапный.

**Foundation + screening**:
- DSST DESIGN ScenarioConfig;
- numerical VALIDATION ScenarioConfig;
- полный explicit `PreviewOptimalOperationsStudyProfile` JSON.

После screening явно выберите candidate.

**Authority + robustness + decision**:
- robustness campaign config;
- explicit hybrid validation output step;
- explicit screening bracket padding;
- полный `PreviewOperationalDecisionPolicy` JSON.

DSST candidate остаётся screening-only до numerical authority. Final recommendation появляется только из persisted credible evidence после paired robustness/Pareto/decision checks.

### 10. Результаты и идентификация
- обычные Preview результаты: `preview/results/`;
- exact build identity: `preview-manifest.json`;
- release должен быть `Engineering Preview Python 0.2.2`;
- source commit, Orekit revision/SHA и editor invariant должны быть заполнены;
- checksum ZIP поставляется рядом с архивом.

При отзыве инженера фиксируйте source SHA, имя ScenarioConfig, run/study id и соответствующие artifacts.

---

## English

### 1. Launch
1. Extract `engineering-preview-python-0.2.2-win10.zip` locally on Windows 10/11.
2. Ensure Python 3.12 is installed. Never copy `.venv-preview` between PCs.
3. Run `start-preview.bat`.
4. Bootstrap creates the local environment and starts bundled Java/Orekit 13.1.7.
5. `/health` must report `preview = 0.2.2`.

### 2. Authority
- SCREENING — analytical/synthetic contour; not operational authority.
- DESIGN — Orekit DSST design/screening evidence.
- VALIDATION — Orekit numerical authority.
- DESIGN/VALIDATION are fail-closed; no silent Screening fallback.

### 3. Open and edit ScenarioConfig
Preview 0.2.2 includes a real **Scenario editor** for the complete YAML model.

1. Open a source scenario.
2. Edit any required `ScenarioConfig` fields, including epoch, duration/output step, force model, integrator, constraints, Monte Carlo, constellation/spacecraft, maneuvers and navigation sites.
3. Select **Validate YAML**.
4. Full `ScenarioConfig` validation runs and the resulting force-model fingerprint is shown.
5. Supply a **new** `.yaml/.yml` name.
6. Select **Save and open**.
7. The new file immediately becomes available for normal runs and compatible higher-level workflows.

Existing YAML files cannot be overwritten, preserving canonical inputs and reproducibility.

### 4. Geometry and P1 relative operations
The engineering view exposes `T`, mean `a`, `i`, `Ω`, `u_mean = λ - Ω = M + ω`, Geometry Preflight, `Δu`, drift, `Δs ≈ a_ref·Δu`, proxy velocity, corridor state and boundary forecast.

`u_mean` is a mean phase coordinate, not osculating argument of latitude. `Δu` is distinct from D'Amico `delta_lambda`. `Δs` is an along-track engineering arc proxy, not Cartesian distance.

### 5. Propagation horizon
Scenario / 1 d / 8 d / 30 d / 90 d / 1 y / 5 y / Custom presets change only effective `duration_s`. Use Scenario editor when `output_step_s`, integrator or force model must change.

### 6. P2 Closed-loop control
Supported policies: NO CONTROL, RETURN-TO-CENTER, BOUNDARY-TO-BOUNDARY. All control numbers are supplied explicitly through the control-profile JSON. Correction-capable policies require VALIDATION and Orekit numerical authority.

The accepted P2 chain includes repeated campaigns, resource ledger, ΔV/fuel/lifetime evidence, checkpoint/resume and safe-stop.

### 7. Design
Explicitly select Screening ScenarioConfig, Validation ScenarioConfig and `design_pipeline_config`. Preview routes to the accepted Design application runner.

### 8. Robustness
Explicitly select Validation ScenarioConfig and `robustness_campaign_config`. Preview routes to the accepted numerical Orekit robustness application.

### 9. Optimal Operations 0.2
Stage 1: DSST DESIGN ScenarioConfig + numerical VALIDATION ScenarioConfig + complete explicit `PreviewOptimalOperationsStudyProfile` JSON.

Select one persisted screening candidate explicitly.

Stage 2: robustness config + explicit hybrid validation step + explicit bracket padding + complete `PreviewOperationalDecisionPolicy` JSON.

DSST evidence stays screening-only until numerical authority. Final recommendation comes only from persisted credible evidence after paired robustness, credible Pareto and decision checks.

### 10. Results and build identity
Use `preview-manifest.json` as the package source of truth. It must identify Engineering Preview Python 0.2.2, the exact source commit, Orekit data identity and Scenario editor invariant. The package checksum is shipped alongside the ZIP.
