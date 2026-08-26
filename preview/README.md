# OC GNSS STRUCT CONTROL — Engineering Preview Python 0.1.4

## Русский

### Назначение
Engineering Preview 0.1.4 — экспертная Windows-версия для проверки сценариев, физической постановки, расчётной authority, геометрии ОГ, относительной динамики, длительных горизонтов и инженерных отчётов.

### Что нового в 0.1.4
- сохранён весь инженерный контур 0.1.3: `T`, `a`, `i`, `Ω`, `u_mean`, Geometry Preflight, `Δu`, `Δs`, скорости дрейфа, фазовый коридор и время до границы;
- добавлены горизонты **1 сут / 8 сут / 30 сут / 90 сут / 1 юлианский год / 5 юлианских лет / custom**;
- интерфейс заранее показывает выбранную длительность, неизменный `output_step_s` и ожидаемое число выходных точек;
- прогноз числа точек следует фактическому контракту сетки: `ceil(duration_s / output_step_s) + 1`, включая точную конечную точку при некратном горизонте;
- выбор горизонта меняет только эффективный `duration_s` запуска;
- fidelity mode, force model/fingerprint, integrator, `output_step_s`, epoch/frame/time scale, геометрия ОГ и манёвры не меняются скрыто;
- исходный YAML не перезаписывается; фактический эффективный сценарий сохраняется в `scenario.normalized.json` результата;
- сокращение горизонта, которое оставило бы заданный манёвр за пределами расчёта, отклоняется полной валидацией `ScenarioConfig`;
- никакого автоматического огрубления шага или downgrade fidelity нет.

### Физическая семантика
`u_mean = λ - Ω = M + ω` — средняя фазовая координата, не оскулирующий аргумент широты.

`Δu` — разность средних фаз дополнительного и опорного КА. Она не тождественна D'Amico `delta_lambda`.

`Δs ≈ a_ref·Δu` — инженерная оценка средней вдольорбитальной дуги, а не декартово физическое расстояние.

Прогноз времени до границы — линейная диагностика по текущей `Δu`, её вековой скорости и `constraints.phase_corridor_rad`, а не решение замкнутого контура управления.

### Быстрый запуск Windows 10
1. Установите Python 3.12 для текущего пользователя, если он отсутствует.
2. Распакуйте ZIP в локальный каталог и запустите `start-preview.bat`.
3. Launcher создаст локальную `.venv-preview`; не копируйте готовую `.venv-preview` между компьютерами.
4. Для DESIGN/VALIDATION требуется Java 17+ и включённый в bundle проверенный Orekit runtime/data.
5. Выберите сценарий и проверьте **Расчётную authority** и **Проверку геометрии ОГ**.
6. Выберите горизонт. Перед запуском убедитесь, что UI показывает ожидаемые `duration`, `output step` и число точек.
7. Запустите расчёт и изучите **Относительную динамику и границу коррекции**, графики и инженерный отчёт.

### Fidelity
- **SCREENING** — Python analytical/synthetic mean-element authority.
- **DESIGN** — Orekit DSST authority.
- **VALIDATION** — Orekit Numerical authority.

High-fidelity режимы работают fail-closed: выбор длинного горизонта никогда не разрешает подмену DESIGN/VALIDATION на SCREENING.

Preview привязан к localhost. Результаты UI сохраняются в `preview/results/`.

---

## English

### Purpose
Engineering Preview 0.1.4 is an expert-facing Windows build for validating scenarios, computation authority, constellation geometry, relative operations, long propagation horizons and engineering reports.

### What is new in 0.1.4
- retains the full 0.1.3 engineering surface: `T`, `a`, `i`, `Ω`, `u_mean`, Geometry Preflight, `Δu`, `Δs`, drift rates, phase corridor and time-to-boundary;
- adds explicit horizons **1 d / 8 d / 30 d / 90 d / 1 Julian year / 5 Julian years / custom**;
- the UI shows selected duration, unchanged `output_step_s`, and predicted output sample count before execution;
- sample-count forecast follows the actual grid contract: `ceil(duration_s / output_step_s) + 1`, including the exact final point for a non-divisible horizon;
- selecting a horizon changes only the effective run `duration_s`;
- fidelity mode, force model/fingerprint, integrator, `output_step_s`, epoch/frame/time scale, constellation geometry and maneuvers are not silently changed;
- source YAML is never overwritten; the effective run scenario is persisted as `scenario.normalized.json`;
- shortening a horizon below a configured maneuver epoch is rejected by full `ScenarioConfig` validation;
- there is no automatic step coarsening or fidelity downgrade.

### Physics semantics
`u_mean = λ - Ω = M + ω` is a mean phase coordinate, not osculating argument of latitude.

`Δu` is the additional/reference mean-phase difference and remains distinct from D'Amico `delta_lambda`.

`Δs ≈ a_ref·Δu` is a mean along-track arc engineering proxy, not Cartesian physical separation.

Time-to-boundary is a linear diagnostic forecast from current `Δu`, its secular rate and `constraints.phase_corridor_rad`; it is not a closed-loop control decision.

### Windows 10 quick start
1. Install Python 3.12 for the current user if needed.
2. Extract the ZIP locally and run `start-preview.bat`.
3. Let the launcher create `.venv-preview`; do not copy a prepared virtual environment between PCs.
4. DESIGN/VALIDATION require Java 17+ and the verified bundled Orekit runtime/data.
5. Select a scenario and inspect **Authority** and **Constellation Geometry Preflight**.
6. Select a horizon and verify displayed duration, output step and predicted sample count.
7. Run the scenario and inspect **Relative operations and correction boundary**, plots and the Engineering report.

### Fidelity
- **SCREENING** — Python analytical/synthetic mean-element authority.
- **DESIGN** — Orekit DSST authority.
- **VALIDATION** — Orekit Numerical authority.

High-fidelity execution remains fail-closed: a long-duration selection never permits silent fallback from DESIGN/VALIDATION to SCREENING.

The Preview binds to localhost. UI run evidence is stored under `preview/results/`.
