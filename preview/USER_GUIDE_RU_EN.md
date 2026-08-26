# OC GNSS STRUCT CONTROL — Engineering Preview Python 0.1.3
# Руководство пользователя / User Guide

## Русский

### 1. Запуск
1. Распакуйте ZIP в локальный каталог Windows 10.
2. Убедитесь, что установлен Python 3.12.
3. Для Design/Validation дополнительно требуется Java 17+.
4. Запустите `start-preview.bat`.
5. Откроется локальный Preview.

На каждом новом компьютере launcher должен создать `.venv-preview` заново. Не копируйте готовую `.venv-preview` с другой машины: virtualenv может содержать абсолютный путь к исходному Python.

### 2. Java Runtime без прав администратора
Для корпоративных компьютеров рекомендуется portable Java.

Не требуется установка через MSI, права администратора и изменение системного PATH.

Структура:

```
runtime/
  java17/
    bin/
      java.exe
```

Проверка:

```powershell
runtime\java17\bin\java.exe -version
```

Ожидаемый результат:

```
openjdk version "17.x.x"
```

Orekit JAR уже входит в Engineering Preview. Отдельная установка Orekit не требуется.

### 3. Язык
В правом верхнем углу выберите **Русский** или **English**. Выбор сохраняется в браузере.

### 4. Сценарии
В списке **Сценарий** показываются только YAML, которые проходят проверку как `ScenarioConfig`. Конфигурации Design pipeline и Robustness campaign вынесены в блок **Другие YAML-входы** и не запускаются кнопкой обычного сценария.

### 5. Authority
Перед запуском проверьте статус:
- SCREENING — Python analytical/synthetic mean-element authority;
- DESIGN — требуется Orekit DSST;
- VALIDATION — требуется Orekit Numerical.

Если Design/Validation показывают **НЕ ГОТОВО**, запуск high fidelity не должен подменяться Screening. Проверьте Java 17+, `preview/runtime/orekit-service.jar` и `preview/runtime/orekit-data/`.

### 6. Инженерный вид орбиты
Основная таблица КА показывает производные от авторитетных средних эквиноциальных элементов:
- `T, ч` — период, вычисленный из средней большой полуоси и `mu` сценария;
- `a, км` — средняя большая полуось;
- `i, °` — наклонение;
- `Ω, °` — RAAN;
- `u_mean, ° = λ - Ω` — средняя фазовая координата `M + ω`;
- массу и запас топлива.

Важно: `u_mean` — не оскулирующий аргумент широты. Исходные `ex/ey/ix/iy/lambda_rad` всегда остаются доступными в **Эксперт / YAML** и **Нормализованный сценарий**.

### 7. Проверка геометрии ОГ
Перед расчётом изучите блок **Проверка геометрии ОГ**. Он показывает фактическую геометрию входного сценария, не навязывая нормативные значения:
- число плоскостей и КА;
- средний RAAN и наклонение каждой плоскости;
- средний внутриплоскостной шаг по `u_mean`;
- `ΔΩ` относительно первой плоскости;
- фазовый сдвиг modulo slot для равнонаселённых регулярных плоскостей.

Если ожидаемая схема ОГ, например 8 КА × 45° и межплоскостное фазирование 0/15/30°, не совпадает с фактической, сценарий следует проверить до длительного расчёта.

### 8. Относительная динамика и граница коррекции
После завершения расчёта Preview показывает для каждой пары `additional/reference`:
- `Δu, °` — конечную разность средних фазовых координат `u_mean`;
- `дрейф, °/сут` и `°/год` — линейную вековую оценку изменения `Δu`;
- `Δs, км ≈ a_ref·Δu` — среднюю вдольорбитальную дуговую оценку;
- `Δv вдоль, м/с` — скорость изменения этой дуговой оценки;
- `±коридор, °` — фактический `constraints.phase_corridor_rad`, переведённый в градусы;
- состояние **В коридоре** или **ВНЕ КОРИДОРА**;
- прогнозируемую сторону границы и время до неё в сутках.

`Δu` не следует смешивать с D'Amico `delta_lambda`: это разные относительные координаты. В D'Amico `delta_lambda` присутствует вклад `cos(i_ref)·ΔΩ`.

`Δs` не является декартовым расстоянием между КА. Для физического расстояния используются Cartesian states и отдельная метрика pair distance.

Если вековая скорость `Δu` равна нулю, Preview показывает неопределённое время до границы вместо искусственно заданного значения. Если КА уже вне коридора, время до границы равно нулю.

Под таблицей доступны:
- **График Δu и коридора**;
- **График Δs**;
- **Интерактивный Δu**.

Эти данные являются диагностикой. В 0.1.3 они ещё не запускают автоматически коррекцию и не выбирают стратегию управления.

### 9. Проверка входных данных
Перед расчётом просмотрите:
- эпоху, frame и time scale;
- длительность и шаг;
- force-model fingerprint;
- инженерную таблицу КА;
- **Проверку геометрии ОГ**;
- **Эксперт / YAML**;
- **Нормализованный сценарий**.

### 10. Запуск и результаты
Нажмите **Запустить выбранный сценарий**. После завершения появятся блок относительной динамики, ссылки на новые графики и ссылка **Открыть инженерный отчёт**. Результаты сохраняются в `preview/results/`.

### 11. Физическое правило
Вековое поведение оценивается по средним элементам, согласованным с той же моделью сил. Мгновенная оскулирующая большая полуось не используется как критерий векового ухода/управления. Cartesian state применяется для истинных физических расстояний, навигационной геометрии и ground track.

### 12. Обратная связь
Заполняйте `preview/EXPERT_FEEDBACK.md` либо присылайте: сценарий → действие → ожидаемый результат → фактический результат → замечание.

---

## English

### 1. Start
1. Extract the ZIP to a local Windows 10 directory.
2. Make sure Python 3.12 is installed.
3. Design/Validation additionally require Java 17+.
4. Run `start-preview.bat`.
5. The local Preview opens.

Let the launcher create `.venv-preview` again on every new computer. Do not copy an already-created environment from another machine because a virtualenv may contain an absolute path to the source Python installation.

### 2. Portable Java without administrator rights
For corporate Windows environments use portable Java.

MSI installation, administrator rights and system PATH changes are not required.

Recommended layout:

```
runtime/
  java17/
    bin/
      java.exe
```

Verify:

```powershell
runtime\java17\bin\java.exe -version
```

Expected:

```
openjdk version "17.x.x"
```

Orekit JAR is already included in Engineering Preview. No separate Orekit installation is required.

### 3. Language
Select **Русский** or **English** in the upper-right corner. The choice is stored in the browser.

### 4. Scenarios
The **Scenario** selector contains only YAML files that validate as `ScenarioConfig`. Design pipeline and Robustness campaign configurations are listed under **Other YAML inputs** and are not executed with the normal scenario button.

### 5. Authority
Check the status before execution:
- SCREENING — Python analytical/synthetic mean-element authority;
- DESIGN — Orekit DSST required;
- VALIDATION — Orekit Numerical required.

If Design/Validation show **NOT READY**, high fidelity must not silently fall back to Screening. Check Java 17+, `preview/runtime/orekit-service.jar`, and `preview/runtime/orekit-data/`.

### 6. Engineering orbit view
The primary spacecraft table displays quantities derived from authoritative mean equinoctial elements:
- `T, h` — period derived from mean semi-major axis and scenario `mu`;
- `a, km` — mean semi-major axis;
- `i, deg` — inclination;
- `Ω, deg` — RAAN;
- `u_mean, deg = λ - Ω` — mean phase coordinate `M + ω`;
- mass and propellant.

Important: `u_mean` is not an osculating argument of latitude. Raw `ex/ey/ix/iy/lambda_rad` remain available under **Expert / YAML** and **Normalized scenario**.

### 7. Constellation Geometry Preflight
Before a long run inspect **Constellation Geometry Preflight**. It reports the observed scenario geometry without inventing target requirements:
- number of planes and spacecraft;
- mean RAAN and inclination per plane;
- mean in-plane `u_mean` spacing;
- `ΔΩ` relative to the first plane;
- phase offset modulo slot size for equal-population regular planes.

If the intended constellation geometry, for example 8 spacecraft × 45° and 0/15/30° inter-plane phasing, differs from the observed values, review the scenario before a long propagation.

### 8. Relative operations and correction boundary
After a run the Preview reports for every `additional/reference` pair:
- `Δu, deg` — final difference between the two mean `u_mean` phase coordinates;
- drift in `deg/day` and `deg/year` — linear secular estimate of `Δu` evolution;
- `Δs, km ≈ a_ref·Δu` — mean along-track arc proxy;
- along-track `Δv, m/s` — rate of that proxy;
- `±corridor, deg` — actual configured `constraints.phase_corridor_rad` converted to degrees;
- **Inside corridor** or **OUTSIDE CORRIDOR** state;
- predicted boundary sign and time to boundary in days.

Do not confuse `Δu` with D'Amico `delta_lambda`; they are distinct relative coordinates. D'Amico `delta_lambda` includes a `cos(i_ref)·ΔΩ` contribution.

`Δs` is not Cartesian spacecraft separation. Physical separation continues to use Cartesian states and the separate pair-distance metric.

If secular `Δu` rate is zero, Preview leaves time-to-boundary unavailable instead of inventing a value. If the pair is already outside the corridor, time-to-boundary is zero.

Below the table the Preview exposes:
- **Δu and corridor plot**;
- **Δs plot**;
- **Interactive Δu**.

These are diagnostics. Version 0.1.3 does not automatically execute a correction or choose a control strategy.

### 9. Input review
Before a run inspect:
- epoch, frame and time scale;
- duration and output step;
- force-model fingerprint;
- engineering spacecraft table;
- **Constellation Geometry Preflight**;
- **Expert / YAML**;
- **Normalized scenario**.

### 10. Run and results
Click **Run selected scenario**. After completion inspect the relative-operations block, the new plots and **Open engineering report**. Run evidence is retained under `preview/results/`.

### 11. Physics rule
Secular behavior is evaluated using mean elements consistent with the same force model. Instantaneous osculating semi-major axis is not used as a secular drift/control criterion. Cartesian state is used for true physical distance, navigation geometry and ground-track evidence.

### 12. Feedback
Use `preview/EXPERT_FEEDBACK.md` or report: scenario → action → expected result → actual result → engineering comment.
