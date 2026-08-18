# OC GNSS STRUCT CONTROL / constellation-control

## Русский

Платформа для воспроизводимого анализа, моделирования, проектирования и управления устойчивыми орбитальными группировками.

> **Критический инвариант:** мгновенная оскулирующая большая полуось никогда не используется как критерий векового ухода. Сравнение дрейфа и оптимизация выполняются только по средним элементам, определение которых связано с той же конфигурацией модели сил, что используется при распространении движения.

### Режимы точности
- **screening** — двухтельная модель + секулярные скорости первого порядка J2. Только быстрый поиск кандидатов.
- **design** — authoritative Orekit DSST. Зональные/тессеральные гармоники, Солнце/Луна, SRP и согласованное преобразование mean↔osculating.
- **validation** — authoritative Orekit numerical propagation. Полная настроенная гравитация, третьи тела, SRP/затмения и манёвры.

Design/Validation работают fail-closed: при отсутствии проверенного Orekit service нет скрытого перехода на Screening.

### Engineering Preview Windows 10
Текущая экспертная сборка: **Engineering Preview Python 0.1.1**.

- запуск: `start-preview.bat`;
- локальный UI: `http://127.0.0.1:8765`;
- переключение интерфейса: **Русский / English**;
- руководство: `preview/USER_GUIDE_RU_EN.md`;
- двуязычная форма обратной связи: `preview/EXPERT_FEEDBACK.md`.

### Быстрый запуск разработки
Python 3.12+:

```bash
python -m venv .venv
source .venv/bin/activate              # Windows: .venv\Scripts\activate
python -m pip install -U pip
pip install -e '.[dev]'
pytest -q
constellation-control run scenarios/mvp_45deg.yaml --output runs
```

`mvp_45deg.yaml` — **синтетический демонстрационный сценарий**, а не набор эксплуатационных параметров ГНСС. Орбитальные, аппаратные, физические и ограничительные параметры задаются явно через YAML.

### Контракт воспроизводимости
Каждый запуск сохраняет `scenario_id`, детерминированный `run_id`, hash нормализованной конфигурации, версию кода, backend/version, force-model fingerprint, epoch, версии алгоритмов и random seed. Результаты сохраняются в JSON + CSV + Parquet; отчёты — Markdown + HTML.

### Политика документации
Пользовательская, эксплуатационная и проектная документация должна быть доступна на **русском и английском языках**. Новые README/руководства создаются двуязычными либо как явно связанные пары RU/EN. Технические термины, идентификаторы схем и имена полей кода не переводятся, если перевод может изменить их машинный смысл.

См. `preview/README.md`, `preview/USER_GUIDE_RU_EN.md`, `docs/roadmap.md`, `docs/validation.md`.

---

## English

Production-oriented platform for reproducible analysis, modelling, design and control of stable orbital constellations.

> **Critical invariant:** instantaneous osculating semi-major axis is never used as a secular-drift criterion. Drift comparison and design optimisation operate only on mean elements whose definition is bound to the same force-model configuration used by propagation.

### Accuracy modes
- **screening** — two-body + first-order J2 secular rates. Fast candidate search only.
- **design** — authoritative Orekit DSST. Zonal/tesseral gravity, Sun/Moon, SRP and consistent mean↔osculating mapping.
- **validation** — authoritative Orekit numerical propagation. Full configured gravity, third bodies, SRP/eclipses and manoeuvres.

Design/Validation fail closed when the reviewed Orekit service is unavailable; there is no silent fallback to Screening.

### Windows 10 Engineering Preview
Current expert build: **Engineering Preview Python 0.1.1**.

- start: `start-preview.bat`;
- local UI: `http://127.0.0.1:8765`;
- UI language: **Русский / English**;
- guide: `preview/USER_GUIDE_RU_EN.md`;
- bilingual feedback form: `preview/EXPERT_FEEDBACK.md`.

### Development quickstart
Python 3.12+:

```bash
python -m venv .venv
source .venv/bin/activate              # Windows: .venv\Scripts\activate
python -m pip install -U pip
pip install -e '.[dev]'
pytest -q
constellation-control run scenarios/mvp_45deg.yaml --output runs
```

`mvp_45deg.yaml` is a **synthetic demonstration scenario**, not a declaration of operational GNSS constellation parameters. Orbital, spacecraft, force-model and constraint values are supplied explicitly through YAML.

### Reproducibility contract
Every run records `scenario_id`, deterministic `run_id`, normalized config hash, code version, backend identity/version, force-model fingerprint, epoch, algorithm versions and random seed. Core results are written to JSON + CSV + Parquet; reports are emitted as Markdown + HTML.

### Documentation policy
User-facing, operational and project documentation must be available in **Russian and English**. New README/guides are bilingual or maintained as explicitly linked RU/EN pairs. Machine-significant schema identifiers, code field names and canonical technical tokens are not translated when translation could alter their meaning.

See `preview/README.md`, `preview/USER_GUIDE_RU_EN.md`, `docs/roadmap.md`, and `docs/validation.md`.
