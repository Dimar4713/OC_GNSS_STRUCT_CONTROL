# OC GNSS STRUCT CONTROL — Engineering Preview Python 0.2.3

## Русский

### Назначение
Engineering Preview 0.2.3 — консолидированная инженерная Windows-версия после восстановления canonical `main`, дополнительно стабилизированная по реальному clean-Windows запуску Orekit sidecar. Она включает весь принятый функционал P0–P3, Design, Robustness и Optimal Operations, а также безопасное редактирование полного `ScenarioConfig`.

### Что входит
- инженерное представление ОГ: `T`, средняя `a`, `i`, `Ω`, `u_mean`, Geometry Preflight;
- относительная динамика: `Δu`, `Δs`, скорости дрейфа, фазовый коридор, прогноз границы, периодические компоненты и инженерные отчёты;
- горизонты propagation: scenario / 1 d / 8 d / 30 d / 90 d / 1 y / 5 y / custom;
- P2 closed-loop: `NO CONTROL`, `RETURN-TO-CENTER`, `BOUNDARY-TO-BOUNDARY`, numerical maneuver authority, повторные циклы, ΔV/топливо/lifetime evidence, checkpoint/resume/safe-stop;
- Design workflow через существующий authoritative application runner;
- Robustness workflow через существующий numerical Orekit campaign;
- P3 Optimal Operations: DSST screening, numerical hybrid authority, optimized long-horizon campaign, paired robustness, credible Pareto и явная decision policy;
- **полный редактор ScenarioConfig YAML**: можно изменить эпоху, duration/output step, force model, integrator, constraints, Monte Carlo, ОГ, параметры КА и maneuvers.

### Редактирование сценария
1. Выберите и откройте исходный сценарий.
2. В блоке **Редактор сценария / Scenario editor** измените полный YAML.
3. Нажмите **Проверить YAML / Validate YAML**. Preview выполняет полную `ScenarioConfig` validation и показывает новый force-model fingerprint.
4. Укажите новое имя `.yaml/.yml` и нажмите **Сохранить и открыть**.
5. Исходные и существующие YAML **никогда не перезаписываются**. Изменённый сценарий сохраняется только как новый файл и сразу появляется в списке для запуска.

Это позволяет реально менять не только горизонт, но и `output_step_s`, force model, integrator, constraints, Monte Carlo и параметры орбитальной группировки/КА.

### Authority
- **SCREENING** — аналитическая/synthetic mean-element authority; не operational authority.
- **DESIGN** — Orekit DSST; используется для screening/design evidence.
- **VALIDATION** — Orekit numerical authority.
- Screening candidate не становится operationally credible от действия UI.
- High-fidelity режимы fail-closed; silent fallback запрещён.

`u_mean = λ - Ω = M + ω` — средняя фазовая координата, не оскулирующий аргумент широты. `Δu` не тождественна D'Amico `delta_lambda`. `Δs ≈ a_ref·Δu` — вдольорбитальная инженерная оценка, не Cartesian distance.

### Быстрый запуск Windows 10/11
1. Распакуйте `engineering-preview-python-0.2.3-win10.zip` в локальный каталог.
2. На ПК должен быть доступен Python 3.12. Готовую `.venv-preview` между компьютерами не переносить.
3. Запустите `start-preview.bat`.
4. Bootstrap создаст локальную `.venv-preview`; реальный launcher повторно экспортирует pinned `OREKIT_DATA_REVISION`, проверит physical SHA и поднимет Orekit 13.1.7.
5. Если на `127.0.0.1:8081` остался старый распознанный `orekit-service.jar`, launcher безопасно завершит только этот stale Java-sidecar и выполнит чистый старт. Посторонний процесс на 8081 автоматически не завершается.
6. Откройте локальный Preview URL, показанный launcher.
7. Проверьте `/health`: версия должна быть `0.2.3`.
8. Для DESIGN/VALIDATION убедитесь, что authority показывает Orekit 13.1.7 и состояние ГОТОВО.

При ошибке authority launcher теперь выводит фактически полученные Orekit version/revision/SHA и хвост stderr непосредственно в консоль.

### Идентификация сборки
Источник истины — `preview-manifest.json` в корне распакованного пакета. Для 0.2.3 в нём должны совпадать:
- release: `Engineering Preview Python 0.2.3`;
- exact source commit;
- Python package version `0.2.3`;
- Orekit version/data revision/data SHA;
- Scenario editor invariant;
- clean-Windows sidecar invariant;
- имя ZIP/artifact `engineering-preview-python-0.2.3-win10`.

Результаты Preview сохраняются в `preview/results/`.

---

## English

### Purpose
Engineering Preview 0.2.3 is the consolidated Windows engineering build after restoring canonical `main`, additionally stabilized for the real clean-Windows Orekit-sidecar startup path. It contains the accepted P0–P3, Design, Robustness and Optimal Operations functionality plus safe full-`ScenarioConfig` editing.

### Included functionality
- constellation engineering view: `T`, mean `a`, `i`, `Ω`, `u_mean`, Geometry Preflight;
- relative operations: `Δu`, `Δs`, drift rates, phase corridor/boundary forecast, periodic components and engineering reports;
- propagation horizons: scenario / 1 d / 8 d / 30 d / 90 d / 1 y / 5 y / custom;
- P2 closed loop: NO CONTROL / RETURN-TO-CENTER / BOUNDARY-TO-BOUNDARY, numerical maneuver authority, repeated cycles, ΔV/fuel/lifetime evidence, checkpoint/resume/safe-stop;
- accepted Design and Robustness application workflows;
- P3 Optimal Operations with DSST screening, numerical hybrid authority, optimized long-horizon campaign, paired robustness, credible Pareto and explicit decision policy;
- **complete ScenarioConfig YAML editor** for epoch, duration/output step, force model, integrator, constraints, Monte Carlo, constellation/spacecraft and maneuvers.

### Scenario editing
1. Open a source scenario.
2. Edit the complete YAML in **Scenario editor**.
3. Select **Validate YAML**. Full `ScenarioConfig` validation runs and the resulting force-model fingerprint is shown.
4. Supply a new `.yaml/.yml` name and select **Save and open**.
5. Existing/canonical YAML files are **never overwritten**. A valid edit is saved only as a new file and becomes immediately selectable/runnable.

### Authority
- **SCREENING** — analytical/synthetic mean-element authority; never operational authority.
- **DESIGN** — Orekit DSST screening/design evidence.
- **VALIDATION** — Orekit numerical authority.
- UI selection cannot promote a screening candidate to operational credibility.
- High-fidelity execution is fail-closed; silent fallback is forbidden.

`u_mean = λ - Ω = M + ω` is a mean phase coordinate, not osculating argument of latitude. `Δu` remains distinct from D'Amico `delta_lambda`. `Δs ≈ a_ref·Δu` is a mean along-track engineering proxy, not Cartesian distance.

### Windows 10/11 quick start
1. Extract `engineering-preview-python-0.2.3-win10.zip` locally.
2. Python 3.12 must be available on the target PC. Never copy `.venv-preview` between PCs.
3. Run `start-preview.bat`.
4. Bootstrap creates the local environment; the real launcher independently reasserts pinned `OREKIT_DATA_REVISION`, verifies physical SHA and starts Orekit 13.1.7.
5. A recognized stale `orekit-service.jar` listener on `127.0.0.1:8081` is stopped before a clean launch. An unrelated process on 8081 is never terminated automatically.
6. Open the local Preview URL printed by the launcher.
7. `/health` must report `0.2.3`.
8. DESIGN/VALIDATION should report Orekit 13.1.7 and READY authority.

On authority failure, the launcher now prints the actual Orekit version/revision/SHA plus the stderr tail directly in the console.

### Build identity
`preview-manifest.json` is the package source of truth. For 0.2.3 it binds release name, exact source commit, Python package version, Orekit version/data identity, scenario-editor invariant, clean-Windows-sidecar invariant and the `engineering-preview-python-0.2.3-win10` artifact name.

Preview evidence is stored under `preview/results/`.
