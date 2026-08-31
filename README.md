# OC GNSS STRUCT CONTROL / constellation-control

## Русский

Платформа для воспроизводимого анализа, моделирования, проектирования и управления устойчивыми орбитальными группировками.

> **Критический инвариант:** мгновенная оскулирующая большая полуось никогда не используется как критерий векового ухода. Дрейф и оптимизация выполняются только в согласованных средних элементах.

### Режимы точности

- **screening** — быстрая аналитическая оценка.
- **design** — Orekit DSST high-fidelity.
- **validation** — Orekit numerical propagation.

Design/Validation работают fail-closed: без проверенного Orekit runtime нет скрытого перехода на Screening.

### Engineering Preview Windows 10/11

Текущая стабильная экспертная сборка: **Engineering Preview Python 0.2.3**.

Текущая ветка функционального развития: **0.2.4** — инженерский ввод ОГ, цифровой двойник, Walker/osculating input, XLS/XLSX и Perturbation Designer. До отдельного release evidence 0.2.4 не считается новой стабильной сборкой.

Запуск:

```text
start-preview.bat
```

UI:

```text
http://127.0.0.1:8765
```

Интерфейс: **Русский / English**.

### Java Runtime для Design/Validation

Для SCREENING установка Java не требуется.

Для DESIGN, VALIDATION, MPC, Robustness и Top-K validation требуется Java Runtime 17+.

Orekit уже входит в состав Preview. Устанавливать Orekit отдельно не нужно.

#### Установка без прав администратора Windows

Рекомендуется portable ZIP-версия OpenJDK 17 LTS.

1. Скачать OpenJDK 17 x64 ZIP.
2. Распаковать, например:

```text
OC_GNSS_STRUCT_CONTROL/
 └─ runtime/
    └─ java17/
       └─ bin/
          └─ java.exe
```

3. Проверить:

```powershell
runtime\java17\bin\java.exe -version
```

Ожидается:

```text
openjdk version "17.x.x"
```

Не требуется:

- права администратора;
- установка в Program Files;
- изменение системного PATH;
- изменение реестра Windows.

### Документация

Вся пользовательская и проектная документация ведётся на русском и английском языках.

Инженерская история изменений: `docs/engineering/change-history.md`.

---

## English

Production-oriented platform for reproducible analysis, modelling, design and control of stable orbital constellations.

> **Critical invariant:** instantaneous osculating semi-major axis is never used as a secular drift criterion. Drift and optimisation operate only on consistent mean elements.

### Accuracy modes

- **screening** — fast analytical assessment.
- **design** — Orekit DSST high-fidelity.
- **validation** — Orekit numerical propagation.

Design/Validation fail closed when reviewed Orekit runtime is unavailable.

### Engineering Preview Windows 10/11

Current stable expert build: **Engineering Preview Python 0.2.3**.

Current functional-development line: **0.2.4** — engineering constellation input, digital twin, Walker/osculating input, XLS/XLSX and Perturbation Designer. Version 0.2.4 is not a new stable package until separate release evidence is completed.

Start:

```text
start-preview.bat
```

UI:

```text
http://127.0.0.1:8765
```

Interface language: **Русский / English**.

### Java Runtime for Design/Validation

Java is not required for SCREENING mode.

Java Runtime 17+ is required for DESIGN, VALIDATION, MPC, Robustness and Top-K validation.

Orekit is already included in Preview. Separate Orekit installation is not required.

#### Installation without Windows administrator rights

Use a portable ZIP distribution of OpenJDK 17 LTS.

1. Download OpenJDK 17 x64 ZIP.
2. Extract, for example:

```text
OC_GNSS_STRUCT_CONTROL/
 └─ runtime/
    └─ java17/
       └─ bin/
          └─ java.exe
```

3. Verify:

```powershell
runtime\java17\bin\java.exe -version
```

Expected:

```text
openjdk version "17.x.x"
```

No administrator rights are required:

- no Program Files installation;
- no system PATH modification;
- no registry changes.

### Documentation policy

All user-facing and project documentation is maintained in Russian and English.

Engineering change history: `docs/engineering/change-history.md`.
