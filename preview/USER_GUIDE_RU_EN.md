# OC GNSS STRUCT CONTROL — Engineering Preview Python 0.1.1
# Руководство пользователя / User Guide

## Русский

### 1. Запуск
1. Распакуйте ZIP в локальный каталог Windows 10.
2. Убедитесь, что установлен Python 3.12.
3. Для Design/Validation дополнительно требуется Java 17+.
4. Запустите `start-preview.bat`.
5. Откроется `http://127.0.0.1:8765`.

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

### 6. Проверка входных данных
Перед расчётом просмотрите:
- эпоху, frame и time scale;
- длительность и шаг;
- force-model fingerprint;
- таблицу КА;
- **Эксперт / YAML**;
- **Нормализованный сценарий**.

### 7. Запуск и результаты
Нажмите **Запустить выбранный сценарий**. После завершения появится ссылка **Открыть инженерный отчёт**. Результаты сохраняются в `preview/results/`.

### 8. Физическое правило
Вековое поведение оценивается по средним элементам, согласованным с той же моделью сил. Мгновенная оскулирующая большая полуось не используется как критерий векового ухода/управления. Cartesian state применяется для истинных физических расстояний, навигационной геометрии и ground track.

### 9. Обратная связь
Заполняйте `preview/EXPERT_FEEDBACK.md` либо присылайте: сценарий → действие → ожидаемый результат → фактический результат → замечание.

---

## English

### 1. Start
1. Extract the ZIP to a local Windows 10 directory.
2. Make sure Python 3.12 is installed.
3. Design/Validation additionally require Java 17+.
4. Run `start-preview.bat`.
5. The UI opens at `http://127.0.0.1:8765`.

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

### 6. Input review
Before a run inspect:
- epoch, frame and time scale;
- duration and output step;
- force-model fingerprint;
- spacecraft table;
- **Expert / YAML**;
- **Normalized scenario**.

### 7. Run and results
Click **Run selected scenario**. After completion use **Open engineering report**. Run evidence is retained under `preview/results/`.

### 8. Physics rule
Secular behavior is evaluated using mean elements consistent with the same force model. Instantaneous osculating semi-major axis is not used as a secular drift/control criterion. Cartesian state is used for true physical distance, navigation geometry and ground-track evidence.

### 9. Feedback
Use `preview/EXPERT_FEEDBACK.md` or report: scenario → action → expected result → actual result → engineering comment.
