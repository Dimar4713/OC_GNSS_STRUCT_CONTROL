# OC GNSS STRUCT CONTROL — Engineering Preview Python 0.1.4
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

Основной инженерный вид показывает `T`, `a`, `i`, `Ω`, `u_mean = λ - Ω`. `u_mean = M + ω` — средняя фазовая координата, не оскулирующий аргумент широты. Исходные эквиноциальные элементы остаются в **Эксперт / YAML** и **Нормализованный сценарий**.

### 3. Проверка геометрии ОГ
**Проверка геометрии ОГ** показывает фактические число плоскостей/КА, средние RAAN и наклонение, внутриплоскостной шаг `u_mean` и межплоскостное фазирование. Она не придумывает нормативную геометрию.

### 4. Выбор горизонта расчёта
В 0.1.4 доступны:
- **Scenario** — длительность из YAML;
- **1 d** — 86 400 с;
- **8 d** — 691 200 с;
- **30 d** — 2 592 000 с;
- **90 d** — 7 776 000 с;
- **1 y** — 31 557 600 с (юлианский год);
- **5 y** — 157 788 000 с;
- **Custom** — положительное конечное значение в секундах.

После выбора Preview показывает:
- эффективный `duration_s`;
- **неизменный** `output_step_s`;
- ожидаемое число выходных точек.

Число точек вычисляется по действующему контракту сетки: `ceil(duration_s / output_step_s) + 1`. Если горизонт не кратен шагу, backend добавляет точную конечную точку.

#### Жёсткий инвариант
Выбор горизонта меняет только эффективный `duration_s`. Не меняются скрыто:
- fidelity / `force_model.mode`;
- force model и его fingerprint;
- integrator;
- `output_step_s`;
- epoch, frame, time scale;
- геометрия ОГ;
- заданные манёвры.

Исходный YAML не перезаписывается. Эффективный сценарий сохраняется в результате как `scenario.normalized.json`.

Если сокращённый горизонт оказался меньше времени уже заданного манёвра, запуск отклоняется валидацией. Preview **не** переносит манёвр, не удаляет его и не расширяет горизонт автоматически.

Preview также не выполняет автоматическое огрубление output step для 1- или 5-летнего расчёта. Большое число точек показывается оператору до запуска.

### 5. Относительная динамика
После расчёта для каждой пары `additional/reference` показываются:
- `Δu, °`;
- вековой дрейф `°/сут` и `°/год`;
- `Δs, км ≈ a_ref·Δu`;
- вдольорбитальная proxy-скорость, м/с;
- настроенный фазовый коридор;
- состояние внутри/вне коридора;
- прогнозируемая граница и время до неё.

`Δu` не тождественна D'Amico `delta_lambda`. `Δs` — средняя дуговая инженерная оценка, не Cartesian distance.

Периодические компоненты отчёта имеют собственные period/amplitude/peak-to-peak; peak-to-peak всегда `2 × amplitude`. RSS нескольких компонент не имеет одного физического периода.

### 6. Результаты
После запуска используйте блок **Относительная динамика и граница коррекции**, графики и **Открыть инженерный отчёт**. Результаты сохраняются в `preview/results/`.

### 7. Обратная связь
Используйте `preview/EXPERT_FEEDBACK.md`: сценарий → выбранный горизонт → действие → ожидаемый результат → фактический результат → инженерное замечание.

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

The primary engineering view shows `T`, `a`, `i`, `Ω`, and `u_mean = λ - Ω`. `u_mean = M + ω` is a mean phase coordinate, not osculating argument of latitude. Raw equinoctial elements remain available under **Expert / YAML** and **Normalized scenario**.

### 3. Constellation Geometry Preflight
**Constellation Geometry Preflight** reports observed plane/spacecraft counts, mean RAAN/inclination, in-plane `u_mean` spacing and inter-plane phasing. It does not invent target geometry.

### 4. Propagation horizon
Version 0.1.4 provides:
- **Scenario** — duration declared by YAML;
- **1 d** — 86,400 s;
- **8 d** — 691,200 s;
- **30 d** — 2,592,000 s;
- **90 d** — 7,776,000 s;
- **1 y** — 31,557,600 s (Julian year);
- **5 y** — 157,788,000 s;
- **Custom** — a positive finite duration in seconds.

Before execution the Preview shows:
- effective `duration_s`;
- the **unchanged** `output_step_s`;
- predicted output sample count.

Sample count follows the active grid contract: `ceil(duration_s / output_step_s) + 1`. If the horizon is not divisible by the step, the backend appends the exact final time.

#### Hard invariant
Selecting a horizon changes only effective `duration_s`. It must not silently change:
- fidelity / `force_model.mode`;
- force model or fingerprint;
- integrator;
- `output_step_s`;
- epoch, frame or time scale;
- constellation geometry;
- configured maneuvers.

The source YAML is never overwritten. The effective scenario is retained in run evidence as `scenario.normalized.json`.

If a shortened horizon would place an existing maneuver outside the run duration, validation rejects the run. The Preview does not move/delete the maneuver or extend the horizon automatically.

There is also no automatic output-step coarsening for 1- or 5-year horizons. Large sample counts are exposed to the operator before execution.

### 5. Relative operations
After a run, every `additional/reference` pair exposes:
- `Δu, deg`;
- secular drift in `deg/day` and `deg/year`;
- `Δs, km ≈ a_ref·Δu`;
- along-track proxy rate in m/s;
- configured phase corridor;
- inside/outside state;
- predicted boundary and time-to-boundary.

`Δu` remains distinct from D'Amico `delta_lambda`. `Δs` is a mean-arc engineering proxy, not Cartesian separation.

Periodic report components have their own period/amplitude/peak-to-peak; peak-to-peak is always `2 × amplitude`. The RSS of multiple components has no single physical period.

### 6. Results
After execution inspect **Relative operations and correction boundary**, generated plots and **Open engineering report**. UI evidence is stored under `preview/results/`.

### 7. Feedback
Use `preview/EXPERT_FEEDBACK.md`: scenario → selected horizon → action → expected result → actual result → engineering comment.
