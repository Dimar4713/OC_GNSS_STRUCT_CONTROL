# OC GNSS STRUCT CONTROL — Engineering Preview Python 0.1.2

## Русский

### Назначение
Engineering Preview 0.1.2 — экспертная Windows-версия для проверки сценариев, физической постановки, расчётной authority, геометрии орбитальной группировки, отчётов и рабочего процесса до финальной упаковки продукта.

### Что нового в 0.1.2
- основной операторский вид больше не требует интерпретировать `ix/iy/lambda_rad` вручную;
- для каждого КА показываются период `T`, средняя большая полуось `a`, наклонение `i`, RAAN `Ω` и средняя фазовая координата `u_mean = λ - Ω`;
- добавлен **Geometry Preflight**: количество плоскостей и КА, средние RAAN/наклонения, внутриплоскостной шаг и фактическое межплоскостное фазирование;
- исходные `ex/ey/ix/iy/lambda_rad` сохранены в **Эксперт / YAML** и **Нормализованный сценарий**;
- `u_mean` намеренно не называется оскулирующим аргументом широты: это производная от авторитетных средних эквиноциальных элементов.

### Быстрый запуск Windows 10
1. Установите Python 3.12 для текущего пользователя, если он ещё не установлен.
2. Распакуйте сборку в локальный каталог.
3. Запустите `start-preview.bat`.
4. Launcher создаст локальную `.venv-preview`, установит зафиксированные зависимости и откроет локальный Preview.
5. В интерфейсе выберите **Русский** или **English**. Выбор сохраняется в браузере.
6. Выберите сценарий, проверьте **Расчётную authority**, таблицу КА и **Проверку геометрии ОГ**, затем запускайте расчёт.
7. После завершения откройте **Инженерный отчёт**.

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

`u_mean = λ - Ω` используется в Preview как средняя фазовая координата `M + ω` для инженерного чтения геометрии. Она не подменяет оскулирующий аргумент широты.

### Каталоги
- `scenarios/` — проверенные входные сценарии;
- `preview/results/` — результаты запусков UI;
- `preview/runtime/` — Orekit runtime/data;
- `preview/EXPERT_FEEDBACK.md` — двуязычная форма обратной связи.

---

## English

### Purpose
Engineering Preview 0.1.2 is an expert-facing Windows build for validating scenarios, physics assumptions, computation authority, constellation geometry, reports and workflow before the final product package is frozen.

### What is new in 0.1.2
- the primary operator view no longer requires manual interpretation of `ix/iy/lambda_rad`;
- each spacecraft shows period `T`, mean semi-major axis `a`, inclination `i`, RAAN `Ω`, and mean phase coordinate `u_mean = λ - Ω`;
- **Constellation Geometry Preflight** reports plane/spacecraft counts, mean RAAN/inclination, in-plane spacing and observed inter-plane phasing;
- raw `ex/ey/ix/iy/lambda_rad` remain available under **Expert / YAML** and **Normalized scenario**;
- `u_mean` is deliberately not labelled as osculating argument of latitude: it is derived from authoritative mean equinoctial elements.

### Windows 10 quick start
1. Install Python 3.12 for the current user if it is not already installed.
2. Extract the build into a local directory.
3. Run `start-preview.bat`.
4. The launcher creates a local `.venv-preview`, installs pinned dependencies and opens the local Preview.
5. Select **Русский** or **English** in the UI. The browser remembers the choice.
6. Select a scenario, inspect **Authority**, the spacecraft table and **Constellation Geometry Preflight**, then run the calculation.
7. After completion open the **Engineering report**.

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

`u_mean = λ - Ω` is used by the Preview as the mean phase coordinate `M + ω` for engineering interpretation. It is not a replacement for osculating argument of latitude.

### Directories
- `scenarios/` — validated scenario inputs;
- `preview/results/` — UI run outputs;
- `preview/runtime/` — Orekit runtime/data;
- `preview/EXPERT_FEEDBACK.md` — bilingual expert feedback form.
