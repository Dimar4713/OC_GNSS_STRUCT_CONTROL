# OC GNSS STRUCT CONTROL — Engineering Preview Python 0.1.1

## Русский

### Назначение
Engineering Preview 0.1.1 — экспертная Windows-версия для проверки сценариев, физической постановки, расчётной authority, отчётов и рабочего процесса до финальной упаковки продукта.

### Быстрый запуск Windows 10
1. Установите Python 3.12 для текущего пользователя, если он ещё не установлен.
2. Распакуйте сборку в локальный каталог.
3. Запустите `start-preview.bat`.
4. Launcher создаст `.venv-preview`, установит зафиксированные зависимости и откроет `http://127.0.0.1:8765`.
5. В интерфейсе выберите **Русский** или **English**. Выбор сохраняется в браузере.
6. Выберите сценарий, проверьте блок **Расчётная authority**, YAML и нормализованный сценарий, затем запускайте расчёт.
7. После завершения откройте **Инженерный отчёт**.

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
Engineering Preview 0.1.1 is an expert-facing Windows build for validating scenarios, physics assumptions, computation authority, reports and workflow before the final product package is frozen.

### Windows 10 quick start
1. Install Python 3.12 for the current user if it is not already installed.
2. Extract the build into a local directory.
3. Run `start-preview.bat`.
4. The launcher creates `.venv-preview`, installs pinned dependencies and opens `http://127.0.0.1:8765`.
5. Select **Русский** or **English** in the UI. The browser remembers the choice.
6. Select a scenario, inspect **Authority**, YAML and the normalized scenario, then run the calculation.
7. After completion open the **Engineering report**.

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
