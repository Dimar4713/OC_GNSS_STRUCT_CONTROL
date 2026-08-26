# OC GNSS STRUCT CONTROL — Engineering Preview Python 0.1.3

## Русский

### Назначение
Engineering Preview 0.1.3 — экспертная Windows-версия для проверки сценариев, физической постановки, расчётной authority, геометрии орбитальной группировки, относительной динамики, отчётов и рабочего процесса до финальной упаковки продукта.

### Что нового в 0.1.3
- сохранён инженерный вид 0.1.2: период `T`, средняя большая полуось `a`, наклонение `i`, RAAN `Ω`, `u_mean = λ - Ω` и **Geometry Preflight**;
- после запуска сценария появился блок **«Относительная динамика и граница коррекции»** для каждой пары `additional/reference`;
- оператор видит текущую/конечную `Δu`, вековую скорость её изменения в `°/сут` и `°/год`, вдольорбитальную оценку `Δs` и её скорость;
- граница берётся только из `constraints.phase_corridor_rad`, без скрытых или придуманных эксплуатационных допусков;
- показываются состояние **в коридоре / вне коридора**, прогнозируемая сторона выхода и время до границы в сутках;
- добавлены ссылки на график `Δu` вместе с коридором, график `Δs` и интерактивный `Δu`;
- исходная D'Amico `delta_lambda` сохранена отдельно и не переименовывается в `Δu`;
- генерация инженерных графиков переведена на headless Matplotlib backend, чтобы отчёты не зависели от Tk/GUI на Windows и серверных средах.

### Физическая семантика новых показателей
`u_mean = λ - Ω = M + ω` — средняя фазовая координата, производная от авторитетных средних элементов. Она **не является** оскулирующим аргументом широты.

`Δu` — разность `u_mean` дополнительного КА и его опорного КА. Она не тождественна D'Amico `delta_lambda`, где присутствует член `cos(i_ref)·ΔΩ`.

`Δs ≈ a_ref·Δu` — инженерная оценка средней вдольорбитальной дуги для почти круговой орбиты. Она **не является** декартовым физическим расстоянием между КА; для физических расстояний сохраняется Cartesian authority.

Прогноз времени до границы использует текущую `Δu`, её оценённую вековую скорость и настроенный `phase_corridor_rad`. Это диагностический линейный прогноз, а не решение замкнутого контура управления.

### Быстрый запуск Windows 10
1. Установите Python 3.12 для текущего пользователя, если он ещё не установлен.
2. Распакуйте сборку в локальный каталог.
3. Запустите `start-preview.bat`.
4. Launcher создаст локальную `.venv-preview`, установит зафиксированные зависимости и откроет локальный Preview.
5. В интерфейсе выберите **Русский** или **English**. Выбор сохраняется в браузере.
6. Выберите сценарий, проверьте **Расчётную authority**, таблицу КА и **Проверку геометрии ОГ**, затем запускайте расчёт.
7. После завершения изучите **Относительную динамику и границу коррекции**, графики и **Инженерный отчёт**.

Не переносите уже созданную `.venv-preview` между компьютерами: virtualenv может содержать абсолютную ссылку на базовый Python исходной машины. На новом ПК launcher должен создать окружение заново.

Preview привязан к localhost и по умолчанию не публикует сетевой сервис.

### Режимы fidelity
- **SCREENING** работает только с Python runtime.
- **DESIGN** требует проверенный Orekit DSST sidecar.
- **VALIDATION** требует проверенный Orekit Numerical sidecar.

High-fidelity режимы работают fail-closed: если Java, JAR, orekit-data или их fingerprint не подтверждены, Design/Validation показывают **НЕ ГОТОВО** и не подменяются Screening.

Launcher читает канонические authority-файлы:
- `sidecar/orekit-service/orekit-data-revision.txt`;
- `sidecar/orekit-service/orekit-data-sha256.txt`.

Release bundle содержит `preview/runtime/orekit-service.jar` и проверенный `preview/runtime/orekit-data/`. Для запуска high fidelity требуется Java 17+.

### Правило физической интерпретации
Вековое поведение оценивается по средним элементам, согласованным с используемой моделью сил. Мгновенная оскулирующая большая полуось **не является** критерием векового ухода или управления. Cartesian state используется для физических расстояний, навигационной геометрии и наземной трассы.

### Каталоги
- `scenarios/` — проверенные входные сценарии;
- `preview/results/` — результаты запусков UI;
- `preview/runtime/` — Orekit runtime/data;
- `preview/EXPERT_FEEDBACK.md` — двуязычная форма обратной связи.

---

## English

### Purpose
Engineering Preview 0.1.3 is an expert-facing Windows build for validating scenarios, physics assumptions, computation authority, constellation geometry, relative operations, reports and workflow before the final product package is frozen.

### What is new in 0.1.3
- retains the 0.1.2 engineering view: period `T`, mean semi-major axis `a`, inclination `i`, RAAN `Ω`, `u_mean = λ - Ω`, and **Constellation Geometry Preflight**;
- after a scenario run, a **Relative operations and correction boundary** surface appears for every `additional/reference` pair;
- the operator sees current/final `Δu`, secular rate in `deg/day` and `deg/year`, along-track proxy `Δs`, and its rate;
- the corridor comes only from `constraints.phase_corridor_rad`; no hidden or invented operational tolerance is introduced;
- the UI reports **inside/outside corridor**, predicted boundary sign, and time to boundary in days;
- links expose the `Δu` + corridor plot, the `Δs` plot, and interactive `Δu` evidence;
- the original D'Amico `delta_lambda` remains separate and is not renamed to `Δu`;
- engineering plot generation uses a headless Matplotlib backend so reporting does not depend on Tk/GUI on Windows or server environments.

### Physics semantics of the new indicators
`u_mean = λ - Ω = M + ω` is a mean phase coordinate derived from authoritative mean elements. It is **not** osculating argument of latitude.

`Δu` is the difference between the additional spacecraft `u_mean` and its declared reference spacecraft `u_mean`. It is not identical to D'Amico `delta_lambda`, which contains a `cos(i_ref)·ΔΩ` term.

`Δs ≈ a_ref·Δu` is a near-circular engineering estimate of mean along-track arc. It is **not** Cartesian physical separation; Cartesian state remains the authority for physical distance.

Time-to-boundary uses current `Δu`, its estimated secular rate, and configured `phase_corridor_rad`. This is a diagnostic linear forecast, not a closed-loop control decision.

### Windows 10 quick start
1. Install Python 3.12 for the current user if it is not already installed.
2. Extract the build into a local directory.
3. Run `start-preview.bat`.
4. The launcher creates a local `.venv-preview`, installs pinned dependencies and opens the local Preview.
5. Select **Русский** or **English** in the UI. The browser remembers the choice.
6. Select a scenario, inspect **Authority**, the spacecraft table and **Constellation Geometry Preflight**, then run the calculation.
7. After completion inspect **Relative operations and correction boundary**, the plots and the **Engineering report**.

Do not copy an already-created `.venv-preview` between computers: a virtual environment may retain an absolute reference to the source machine's base Python. Let the launcher create it again on each target PC.

The Preview binds to localhost and does not expose a network service by default.

### Fidelity modes
- **SCREENING** uses the Python runtime only.
- **DESIGN** requires the reviewed Orekit DSST sidecar.
- **VALIDATION** requires the reviewed Orekit Numerical sidecar.

High-fidelity execution is fail-closed: if Java, JAR, orekit-data or its fingerprint cannot be verified, Design/Validation remain **NOT READY** and are never silently replaced by Screening.

The launcher reads canonical authority identity from:
- `sidecar/orekit-service/orekit-data-revision.txt`;
- `sidecar/orekit-service/orekit-data-sha256.txt`.

The release bundle contains `preview/runtime/orekit-service.jar` and verified `preview/runtime/orekit-data/`. Java 17+ is required for high fidelity.

### Physics interpretation rule
Secular behavior is evaluated using force-model-consistent mean elements. Instantaneous osculating semi-major axis is **not** a secular drift/control criterion. Cartesian state is used for physical distance, navigation geometry and ground-track evidence.

### Directories
- `scenarios/` — validated scenario inputs;
- `preview/results/` — UI run outputs;
- `preview/runtime/` — Orekit runtime/data;
- `preview/EXPERT_FEEDBACK.md` — bilingual expert feedback form.
