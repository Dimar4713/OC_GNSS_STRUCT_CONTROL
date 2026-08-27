# OC GNSS STRUCT CONTROL — Engineering Preview Python 0.1.5

## Русский

### Назначение
Engineering Preview 0.1.5 — экспертная Windows-версия для проверки сценариев, физической постановки, расчётной authority, геометрии ОГ, относительной динамики, длительных горизонтов и воспроизводимых P2 closed-loop операций.

### Что нового в 0.1.5
- сохранён весь инженерный контур 0.1.4: `T`, `a`, `i`, `Ω`, `u_mean`, Geometry Preflight, `Δu`, `Δs`, скорости дрейфа, фазовый коридор, время до границы и явные горизонты 1 d…5 y/custom;
- добавлен отдельный блок **Замкнутый контур управления / Closed-loop control**;
- поддержаны только принятые P2 политики: `NO CONTROL`, `RETURN-TO-CENTER`, `BOUNDARY-TO-BOUNDARY`;
- управляющие числа Preview не придумывает: campaign/coast horizons, authority grid/windows, RTN impulse limits, MIB, trust tolerances, target ROE и MPC weights должны быть явно заданы оператором в control-profile JSON;
- correction-capable политики требуют сценарий `VALIDATION` и численную Orekit authority; подмена на Screening запрещена;
- `NO CONTROL` не вызывает maneuver authority;
- UI показывает только принятые backend evidence: termination, corrections, ΔV, propellant, remaining/reserve, annualization/lifetime availability/projection, settling/rearm, authority backend/fingerprint/frame/time scale;
- стандартные доказательства сохраняются как `closed_loop_profile.json`, `closed_loop_campaign.json`, `closed_loop_metrics.json`, `closed_loop_corrections.*`, `report.md/html`.

### Физическая семантика
`u_mean = λ - Ω = M + ω` — средняя фазовая координата, не оскулирующий аргумент широты.

`Δu` — разность средних фаз дополнительного и опорного КА. Она не тождественна D'Amico `delta_lambda`.

`Δs ≈ a_ref·Δu` — инженерная оценка средней вдольорбитальной дуги, а не декартово физическое расстояние.

Фазовый коридор остаётся жёстким operator `Δu` constraint. Screening evidence никогда не разрешает манёвр.

### Быстрый запуск Windows 10
1. Установите Python 3.12 для текущего пользователя, если он отсутствует.
2. Распакуйте ZIP и запустите `start-preview.bat`.
3. Launcher создаст локальную `.venv-preview`; не копируйте готовую `.venv-preview` между компьютерами.
4. Для DESIGN/VALIDATION требуется Java 17+ и включённый в bundle проверенный Orekit runtime/data.
5. Выберите сценарий и проверьте **Расчётную authority** и **Проверку геометрии ОГ**.
6. Для обычной propagation-диагностики используйте существующий P1 запуск и горизонты.
7. Для P2 операций откройте блок **Замкнутый контур управления**, выберите политику и вставьте полный явный control-profile JSON. Preview не заполняет численные control defaults.
8. До запуска проверьте отображённые hard constraints, force-model fingerprint, frame/time scale и authority mode.
9. После closed-loop запуска изучите таблицу evidence и ссылки на стандартные артефакты.

### Fidelity
- **SCREENING** — Python analytical/synthetic mean-element authority.
- **DESIGN** — Orekit DSST authority.
- **VALIDATION** — Orekit Numerical authority.

Correction-capable closed-loop execution работает только с `VALIDATION`. High-fidelity режимы fail-closed; silent fallback запрещён.

Preview привязан к localhost. Результаты UI сохраняются в `preview/results/`.

---

## English

### Purpose
Engineering Preview 0.1.5 is an expert-facing Windows build for scenario/physics validation, explicit computation authority, constellation geometry, relative operations, long horizons and reproducible P2 closed-loop operations.

### What is new in 0.1.5
- retains the full 0.1.4 engineering surface: `T`, `a`, `i`, `Ω`, `u_mean`, Geometry Preflight, `Δu`, `Δs`, drift rates, phase corridor, time-to-boundary and explicit 1 d…5 y/custom horizons;
- adds a separate **Closed-loop control / Замкнутый контур управления** operator section;
- exposes only accepted P2 policies: `NO CONTROL`, `RETURN-TO-CENTER`, `BOUNDARY-TO-BOUNDARY`;
- Preview invents no control numbers: campaign/coast horizons, authority grid/windows, RTN impulse limits, MIB, trust tolerances, target ROE and MPC weights must be supplied explicitly by the operator in control-profile JSON;
- correction-capable policies require a `VALIDATION` scenario and numerical Orekit authority; Screening fallback is forbidden;
- `NO CONTROL` invokes no maneuver authority;
- UI renders accepted backend evidence only: termination, corrections, ΔV, propellant, remaining/reserve, annualization/lifetime availability/projection, settling/rearm, authority backend/fingerprint/frame/time scale;
- standard evidence is retained as `closed_loop_profile.json`, `closed_loop_campaign.json`, `closed_loop_metrics.json`, `closed_loop_corrections.*`, and `report.md/html`.

### Physics semantics
`u_mean = λ - Ω = M + ω` is a mean phase coordinate, not osculating argument of latitude.

`Δu` is the additional/reference mean-phase difference and remains distinct from D'Amico `delta_lambda`.

`Δs ≈ a_ref·Δu` is a mean along-track arc engineering proxy, not Cartesian physical separation.

The phase corridor remains a hard operator `Δu` constraint. Screening evidence can never authorize a maneuver.

### Windows 10 quick start
1. Install Python 3.12 for the current user if needed.
2. Extract the ZIP and run `start-preview.bat`.
3. Let the launcher create `.venv-preview`; do not copy a prepared virtual environment between PCs.
4. DESIGN/VALIDATION require Java 17+ and the verified bundled Orekit runtime/data.
5. Select a scenario and inspect **Authority** and **Constellation Geometry Preflight**.
6. Use the existing P1 run/horizon controls for propagation diagnostics.
7. For P2 operations open **Closed-loop control**, select a policy and paste a complete explicit control-profile JSON. Preview does not prefill numerical control defaults.
8. Before execution inspect the displayed hard constraints, force-model fingerprint, frame/time scale and authority mode.
9. After execution inspect accepted evidence and links to standard artifacts.

### Fidelity
- **SCREENING** — Python analytical/synthetic mean-element authority.
- **DESIGN** — Orekit DSST authority.
- **VALIDATION** — Orekit Numerical authority.

Correction-capable closed-loop execution requires `VALIDATION`. High-fidelity execution remains fail-closed; silent fallback is forbidden.

The Preview binds to localhost. UI run evidence is stored under `preview/results/`.
