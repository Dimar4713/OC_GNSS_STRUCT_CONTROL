# Operator input model / Модель операторских входов

## Зачем это разделение

Engineering Preview использует несколько разных типов входов. Они не являются взаимозаменяемыми и не должны смешиваться в одном списке.

### 1. Runnable ScenarioConfig

`ScenarioConfig` описывает **что моделируется**:

- epoch, frame, time scale;
- constellation and spacecraft;
- force model and Earth gravity degree/order;
- integrator and output step;
- constraints and maneuvers;
- authority-relevant mean-element definitions;
- digital-twin lineage where present.

Только валидный `ScenarioConfig` является runnable scenario.

### 2. Design pipeline config

Design config описывает **как выполняется поиск проектного решения**. Например: bounds, LHS samples, local search, NSGA settings, top-K and recommendation weights.

Он не содержит орбитальную группировку и сам по себе не запускается как ScenarioConfig.

Design run всегда является явной комбинацией:

`SCREENING ScenarioConfig + VALIDATION ScenarioConfig + Design pipeline config`

Интерфейс обязан показывать все три выбранных входа до запуска.

### 3. Robustness campaign config

Robustness config описывает **как проверяется решение на неопределённостях**: samples, seed, scalar/correlated uncertainties, maneuver errors, authority requirements and campaign identity.

Простой robustness run использует явную комбинацию:

`VALIDATION ScenarioConfig + Robustness campaign config`

В optimal-operations workflow дополнительно фиксируется выбранный design candidate.

## Active Run Configuration

В верхней части операторского интерфейса постоянно отображается панель `Active Run Configuration`.

Она показывает:

- текущий runnable scenario;
- force mode;
- Earth gravity model;
- authority;
- force-model fingerprint;
- выбранные Design screening/validation scenarios;
- выбранный Design config;
- выбранные Robustness validation scenario/config.

Смена вкладки не должна неявно менять выбранные расчётные входы.

## Импорт источников

Internet/file import не является runnable scenario автоматически.

Общий путь:

`raw source -> normalized dataset -> authority/semantic checks -> orbital conversion -> force-model-consistent mean elements -> derived ScenarioConfig -> runnable scenario`

Для IAC/GSC/NORAD/almanac источников UI должен явно показывать, на каком этапе находится источник и почему создание runnable scenario разрешено или заблокировано.

Нельзя молча подставлять отсутствующие time-system, health, week/epoch или другие authority semantics.

## Связь модели сил и средних элементов

Mean elements связаны с конкретной теорией и `force_model_fingerprint`. Если изменение force model (включая degree/order ГПЗ) меняет fingerprint, нельзя просто переписать fingerprint у старых mean elements.

Нужен authority-backed re-derive из исходного osculating/TLE/GNSS состояния. Если такого источника/конверсии нет, операция должна завершиться fail-closed **до записи derived YAML**.

## Вкладки Preview 0.2.6

- **Сценарии / Scenarios** — runnable ScenarioConfig, редакторы модели, ОГ, КА и derived copies.
- **Входные данные и импорт / Inputs & Import** — IAC, Galileo GSC, GNSS almanac, GLONASS authority, NORAD/TLE, osculating, Walker, workbook.
- **Design / Проектирование** — явный выбор screening scenario, validation scenario и Design config.
- **Robustness / Робастность** — явный выбор validation scenario и campaign config.
- **Результаты / Results** — результаты, diagnostics, promotion and run evidence.
- **Эксперт / Expert** — raw YAML, normalized representation, hashes/fingerprints and diagnostics.

## Файловая структура

Текущий flat `scenarios/*.yaml` остаётся совместимым на переходном этапе. Планируемая структура должна разделить runnable scenarios и workflow configs физически, но существующие пользовательские файлы не должны перемещаться молча.
