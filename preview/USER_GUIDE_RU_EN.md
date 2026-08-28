# OC GNSS STRUCT CONTROL — Engineering Preview Python 0.1.5
# Руководство пользователя / User Guide

## Русский

### 1. Запуск
1. Распакуйте ZIP в локальный каталог Windows 10.
2. Убедитесь, что установлен Python 3.12; для DESIGN/VALIDATION дополнительно требуется Java 17+.
3. Запустите `start-preview.bat`.
4. На каждом новом компьютере launcher должен создать `.venv-preview` заново — не переносите готовое окружение с другой машины.

### 2. Authority и физическая постановка
Перед расчётом проверьте SCREENING / DESIGN / VALIDATION authority. DESIGN/VALIDATION работают fail-closed: недоступный Orekit не подменяется Screening.

Основной инженерный вид показывает `T`, `a`, `i`, `Ω`, `u_mean = λ - Ω`. `u_mean = M + ω` — средняя фазовая координата, не оскулирующий аргумент широты. Прямая `Δu` не тождественна D'Amico `delta_lambda`.

### 3. Проверка геометрии ОГ
**Проверка геометрии ОГ** показывает фактические число плоскостей/КА, средние RAAN и наклонение, внутриплоскостной шаг `u_mean` и межплоскостное фазирование. Она не придумывает нормативную геометрию.

### 4. Propagation horizon
Доступны Scenario / 1 d / 8 d / 30 d / 90 d / 1 Julian year / 5 Julian years / Custom. Выбор горизонта меняет только эффективный `duration_s`; force model/fingerprint, integrator, `output_step_s`, epoch/frame/time scale, геометрия и манёвры скрыто не меняются. Автоматического огрубления output step нет.

### 5. Относительная динамика P1
После обычного запуска для каждой пары `additional/reference` показываются `Δu`, дрейф, `Δs ≈ a_ref·Δu`, proxy-скорость, коридор, inside/outside и линейный прогноз времени до границы. `Δs` — средняя дуговая оценка, не Cartesian distance.

### 6. Closed-loop control P2
Отдельный блок **Замкнутый контур управления / Closed-loop control** поддерживает `NO CONTROL`, `RETURN-TO-CENTER`, `BOUNDARY-TO-BOUNDARY`.

Preview не содержит численных control defaults. Оператор явно задаёт `campaign_horizon_s`, `coast_horizon_s`, `coast_output_step_s`, `max_corrections`, `authority_times_s`, `maneuver_windows`, `max_abs_impulse_rtn_m_s`, `min_impulse_bit_m_s`, `trust_tolerances_roe`, `target_roe`, `w_tracking`, `w_max` и при необходимости `deputy_id`.

Correction-capable политики разрешены только для `VALIDATION` scenario с настроенной Orekit numerical authority. `NO CONTROL` не вызывает maneuver authority. UI показывает принятые backend evidence, а не пересчитывает ΔV/fuel/lifetime сам.

### 7. Design / Robustness workflows
В блоке **Design / Robustness workflows — Проектирование / Робастность** запускаются существующие application workflows напрямую.

#### 7.1 Design pipeline
Нужно явно выбрать:
1. Screening ScenarioConfig — должен иметь `force_model.mode = screening`;
2. Validation ScenarioConfig — должен иметь `force_model.mode = validation` и доступную Orekit numerical authority;
3. YAML, классифицированный как `design_pipeline_config`.

После **Run Design** Preview вызывает только существующий `run_design_application()`. Screening search не является финальной authority: рекомендация принимается только после предусмотренного pipeline numerical Orekit replay. UI не выполняет собственный optimizer и не пересчитывает recommendation.

Доступные штатные артефакты включают `pipeline_manifest.json`, `recommendation.json`, `validation.json`, `candidates.*`, `pareto.*`, `report.md/html`.

#### 7.2 Robustness campaign
Нужно явно выбрать:
1. Validation ScenarioConfig;
2. YAML, классифицированный как `robustness_campaign_config`.

После **Run Robustness** Preview вызывает только существующий `run_robustness_application()`. Отдельного UI sampler/Monte Carlo нет; uncertainty, seed, workers, authority и accepted candidate берутся из явного campaign config и действующего backend contract.

Доступные штатные артефакты включают `campaign_manifest.json`, `summary.json`, `samples.*`, `outcomes.*`, `statistics.csv`, `violation_probability.csv`, `report.md/html`.

#### 7.3 Fail-closed правила
- неверный YAML-kind отклоняется до application runner;
- Screening ScenarioConfig нельзя передать как Validation input;
- Validation нельзя молча заменить Screening;
- Preview не создаёт design/robustness defaults;
- UI показывает/ссылается на существующие artifacts, а не создаёт параллельную систему доказательств.

### 8. Результаты и обратная связь
Результаты сохраняются в `preview/results/`. Для обратной связи используйте `preview/EXPERT_FEEDBACK.md`: сценарий/config → действие → ожидаемый результат → фактический результат → инженерное замечание.

---

## English

### 1. Start
1. Extract the ZIP to a local Windows 10 directory.
2. Make sure Python 3.12 is installed; DESIGN/VALIDATION additionally require Java 17+.
3. Run `start-preview.bat`.
4. Let the launcher create `.venv-preview` again on every target PC; do not copy a prepared virtual environment between machines.

### 2. Authority and physics
Verify SCREENING / DESIGN / VALIDATION authority before execution. DESIGN/VALIDATION remain fail-closed; unavailable Orekit is never silently replaced by Screening.

The primary engineering view shows `T`, `a`, `i`, `Ω`, and `u_mean = λ - Ω`. `u_mean = M + ω` is a mean phase coordinate, not osculating argument of latitude. Direct `Δu` remains distinct from D'Amico `delta_lambda`.

### 3. Constellation Geometry Preflight
**Constellation Geometry Preflight** reports observed plane/spacecraft counts, mean RAAN/inclination, in-plane `u_mean` spacing and inter-plane phasing. It does not invent target geometry.

### 4. Propagation horizon
Scenario / 1 d / 8 d / 30 d / 90 d / 1 Julian year / 5 Julian years / Custom horizons remain available. Selecting a horizon changes only effective `duration_s`; force model/fingerprint, integrator, `output_step_s`, epoch/frame/time scale, geometry and maneuvers are not silently changed.

### 5. Relative operations P1
After a normal run each `additional/reference` pair exposes `Δu`, drift, `Δs ≈ a_ref·Δu`, along-track proxy rate, corridor state and linear time-to-boundary. `Δs` is a mean-arc engineering proxy, not Cartesian separation.

### 6. Closed-loop control P2
The separate **Closed-loop control / Замкнутый контур управления** section supports `NO CONTROL`, `RETURN-TO-CENTER`, `BOUNDARY-TO-BOUNDARY`.

Preview contains no numerical control defaults. The operator explicitly supplies `campaign_horizon_s`, `coast_horizon_s`, `coast_output_step_s`, `max_corrections`, `authority_times_s`, `maneuver_windows`, `max_abs_impulse_rtn_m_s`, `min_impulse_bit_m_s`, `trust_tolerances_roe`, `target_roe`, `w_tracking`, `w_max`, and optional `deputy_id`.

Correction-capable policies require a `VALIDATION` scenario with configured Orekit numerical authority. `NO CONTROL` invokes no maneuver authority. The UI renders accepted backend evidence rather than recomputing ΔV/fuel/lifetime.

### 7. Design / Robustness workflows
The **Design / Robustness workflows — Проектирование / Робастность** section launches the existing application workflows directly.

#### 7.1 Design pipeline
Explicitly select:
1. a Screening ScenarioConfig with `force_model.mode = screening`;
2. a Validation ScenarioConfig with `force_model.mode = validation` and numerical Orekit authority;
3. YAML classified as `design_pipeline_config`.

**Run Design** routes only to the existing `run_design_application()`. Screening search is not final authority; recommendation requires the pipeline's numerical Orekit replay. The UI has no independent optimizer and does not recompute recommendation evidence.

Standard artifacts include `pipeline_manifest.json`, `recommendation.json`, `validation.json`, `candidates.*`, `pareto.*`, and `report.md/html`.

#### 7.2 Robustness campaign
Explicitly select:
1. a Validation ScenarioConfig;
2. YAML classified as `robustness_campaign_config`.

**Run Robustness** routes only to the existing `run_robustness_application()`. There is no separate UI sampler or Monte Carlo implementation; uncertainty, seed, workers, authority and accepted candidate come from the explicit campaign config and accepted backend contract.

Standard artifacts include `campaign_manifest.json`, `summary.json`, `samples.*`, `outcomes.*`, `statistics.csv`, `violation_probability.csv`, and `report.md/html`.

#### 7.3 Fail-closed rules
- wrong YAML kind is rejected before the application runner;
- a Screening ScenarioConfig cannot be used as a Validation input;
- Validation is never silently replaced with Screening;
- Preview invents no Design/Robustness defaults;
- UI links to existing artifacts instead of creating a parallel evidence system.

### 8. Results and feedback
UI evidence is stored under `preview/results/`. Use `preview/EXPERT_FEEDBACK.md` for scenario/config → action → expected result → actual result → engineering comment.
