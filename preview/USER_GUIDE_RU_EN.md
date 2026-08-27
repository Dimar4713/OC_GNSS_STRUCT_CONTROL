# OC GNSS STRUCT CONTROL — Engineering Preview Python 0.1.5
# Руководство пользователя / User Guide

## Русский

### 1. Запуск
1. Распакуйте ZIP в локальный каталог Windows 10.
2. Убедитесь, что установлен Python 3.12; для DESIGN/VALIDATION дополнительно требуется Java 17+.
3. Запустите `start-preview.bat`.
4. На каждом новом компьютере launcher должен создать `.venv-preview` заново — не переносите готовое окружение с другой машины.

### 2. Authority и физическая постановка
Перед расчётом проверьте:
- **SCREENING** — Python analytical/synthetic mean-element authority;
- **DESIGN** — Orekit DSST authority;
- **VALIDATION** — Orekit Numerical authority.

DESIGN/VALIDATION работают fail-closed: недоступный Orekit не подменяется Screening.

Основной инженерный вид показывает `T`, `a`, `i`, `Ω`, `u_mean = λ - Ω`. `u_mean = M + ω` — средняя фазовая координата, не оскулирующий аргумент широты. `Δu` — прямая разность этой средней фазы и не тождественна D'Amico `delta_lambda`.

### 3. Проверка геометрии ОГ
**Проверка геометрии ОГ** показывает фактические число плоскостей/КА, средние RAAN и наклонение, внутриплоскостной шаг `u_mean` и межплоскостное фазирование. Она не придумывает нормативную геометрию.

### 4. Propagation horizon
Сохраняются горизонты 0.1.4:
- Scenario;
- 1 d / 8 d / 30 d / 90 d;
- 1 Julian year / 5 Julian years;
- Custom.

Выбор горизонта меняет только эффективный `duration_s`. `force_model`, fingerprint, integrator, `output_step_s`, epoch/frame/time scale, геометрия и манёвры скрыто не меняются. Автоматического огрубления output step нет.

### 5. Относительная динамика P1
После обычного запуска для каждой пары `additional/reference` показываются `Δu`, дрейф, `Δs ≈ a_ref·Δu`, proxy-скорость, коридор, inside/outside и линейный прогноз времени до границы.

`Δs` — средняя дуговая инженерная оценка, не Cartesian distance. P1 прогноз времени до границы не является решением closed-loop управления.

### 6. Closed-loop control P2
В 0.1.5 появился отдельный блок **Замкнутый контур управления / Closed-loop control**.

Поддерживаются:
- `NO CONTROL`;
- `RETURN-TO-CENTER`;
- `BOUNDARY-TO-BOUNDARY`.

`OPTIMIZED` относится к P3 и не маскируется под P2 политику.

#### 6.1. Явный control profile
Preview **не содержит численных control defaults**. Перед запуском оператор должен вставить JSON-профиль со всеми требуемыми полями:
- `campaign_horizon_s`;
- `coast_horizon_s`;
- `coast_output_step_s`;
- `max_corrections`;
- `authority_times_s`;
- `maneuver_windows`;
- `max_abs_impulse_rtn_m_s`;
- `min_impulse_bit_m_s`;
- `trust_tolerances_roe`;
- `target_roe`;
- `w_tracking`;
- `w_max`;
- при необходимости `deputy_id`.

Политика выбирается отдельным selector и передаётся в тот же валидируемый `PreviewClosedLoopProfile`. Если обязательного поля нет или значение не проходит P2/MPC contract, запуск отклоняется до authority work.

#### 6.2. Проверка перед запуском
Блок показывает из выбранного ScenarioConfig:
- force mode;
- frame/time scale;
- force-model fingerprint;
- `phase_corridor_rad`;
- `min_pair_distance_m`;
- `propellant_reserve_fraction`.

Correction-capable политики разрешены только для `VALIDATION` scenario с настроенной Orekit numerical authority. Screening/Design не получают скрытого fallback. `NO CONTROL` не вызывает maneuver authority.

#### 6.3. Что показывает результат
UI не пересчитывает физику или ресурсные оценки. Он отображает принятые API/backend evidence:
- policy и termination reason;
- число corrections и authority attempts;
- cumulative ΔV;
- cumulative propellant used;
- remaining propellant и required reserve;
- annualization availability и ΔV/fuel per Julian year, если evidence достаточно;
- lifetime projection availability и projected years to reserve, если evidence поддерживает прогноз;
- rearm/settling availability/reason;
- authority backend(s), force fingerprint, frame/time scale;
- таблицу каждой авторизованной коррекции.

Если annualization/lifetime недоступны, UI показывает `—`/unavailable, а не нулевой риск или нулевое потребление.

#### 6.4. Артефакты
Для closed-loop запуска доступны:
- `closed_loop_profile.json`;
- `closed_loop_campaign.json`;
- `closed_loop_metrics.json`;
- `closed_loop_corrections.json/csv/parquet`;
- `report.md`;
- `report.html`.

Эти файлы публикуются существующим принятым P2 artifact pipeline.

### 7. Результаты и обратная связь
Результаты сохраняются в `preview/results/`. Для обратной связи используйте `preview/EXPERT_FEEDBACK.md`: сценарий → профиль/горизонт → действие → ожидаемый результат → фактический результат → инженерное замечание.

---

## English

### 1. Start
1. Extract the ZIP to a local Windows 10 directory.
2. Make sure Python 3.12 is installed; DESIGN/VALIDATION additionally require Java 17+.
3. Run `start-preview.bat`.
4. Let the launcher create `.venv-preview` again on every target PC; do not copy a prepared virtual environment between machines.

### 2. Authority and physics
Before execution verify:
- **SCREENING** — Python analytical/synthetic mean-element authority;
- **DESIGN** — Orekit DSST authority;
- **VALIDATION** — Orekit Numerical authority.

DESIGN/VALIDATION remain fail-closed; unavailable Orekit is never silently replaced by Screening.

The primary engineering view shows `T`, `a`, `i`, `Ω`, and `u_mean = λ - Ω`. `u_mean = M + ω` is a mean phase coordinate, not osculating argument of latitude. Direct `Δu` remains distinct from D'Amico `delta_lambda`.

### 3. Constellation Geometry Preflight
**Constellation Geometry Preflight** reports observed plane/spacecraft counts, mean RAAN/inclination, in-plane `u_mean` spacing and inter-plane phasing. It does not invent target geometry.

### 4. Propagation horizon
Version 0.1.5 retains the explicit Scenario / 1 d / 8 d / 30 d / 90 d / 1 Julian year / 5 Julian years / Custom horizon controls from 0.1.4.

Selecting a horizon changes only effective `duration_s`. Force model/fingerprint, integrator, `output_step_s`, epoch/frame/time scale, constellation geometry and maneuvers are not silently changed. No automatic output-step coarsening is performed.

### 5. Relative operations P1
After a normal run, every `additional/reference` pair exposes `Δu`, drift, `Δs ≈ a_ref·Δu`, along-track proxy rate, corridor state and linear time-to-boundary forecast.

`Δs` is a mean-arc engineering proxy, not Cartesian separation. P1 time-to-boundary forecast is not a closed-loop control decision.

### 6. Closed-loop control P2
Engineering Preview 0.1.5 adds a separate **Closed-loop control / Замкнутый контур управления** section.

Supported policies:
- `NO CONTROL`;
- `RETURN-TO-CENTER`;
- `BOUNDARY-TO-BOUNDARY`.

`OPTIMIZED` belongs to P3 and is not relabeled as a P2 policy.

#### 6.1 Explicit control profile
The Preview contains **no numerical control defaults**. Before execution the operator must supply JSON containing all required fields:
- `campaign_horizon_s`;
- `coast_horizon_s`;
- `coast_output_step_s`;
- `max_corrections`;
- `authority_times_s`;
- `maneuver_windows`;
- `max_abs_impulse_rtn_m_s`;
- `min_impulse_bit_m_s`;
- `trust_tolerances_roe`;
- `target_roe`;
- `w_tracking`;
- `w_max`;
- optional `deputy_id` when needed.

The policy selector is submitted through the same validated `PreviewClosedLoopProfile`. Missing/invalid values are rejected before authority work.

#### 6.2 Pre-run evidence
The section displays from the selected ScenarioConfig:
- force mode;
- frame/time scale;
- force-model fingerprint;
- `phase_corridor_rad`;
- `min_pair_distance_m`;
- `propellant_reserve_fraction`.

Correction-capable policies require a `VALIDATION` scenario and configured numerical Orekit authority. Screening/Design receive no hidden fallback. `NO CONTROL` invokes no maneuver authority.

#### 6.3 Result evidence
The UI does not recompute physics or resource projections. It renders accepted API/backend evidence only:
- policy and termination reason;
- correction and authority-attempt counts;
- cumulative ΔV;
- cumulative propellant used;
- remaining propellant and required reserve;
- annualization availability and ΔV/fuel per Julian year when supported;
- lifetime projection availability and projected years to reserve when supported;
- rearm/settling availability/reason;
- authority backend(s), force fingerprint, frame/time scale;
- one row per authorized correction.

Unavailable annualization/lifetime remains unavailable (`—`), never converted into zero risk or zero consumption.

#### 6.4 Artifacts
Closed-loop runs expose:
- `closed_loop_profile.json`;
- `closed_loop_campaign.json`;
- `closed_loop_metrics.json`;
- `closed_loop_corrections.json/csv/parquet`;
- `report.md`;
- `report.html`.

These files are produced by the accepted P2 artifact pipeline.

### 7. Results and feedback
UI evidence is stored under `preview/results/`. Use `preview/EXPERT_FEEDBACK.md` for scenario → profile/horizon → action → expected result → actual result → engineering comment.
