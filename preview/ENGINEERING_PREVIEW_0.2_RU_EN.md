# Engineering Preview 0.2.0 — инженерное тестирование / Engineering evaluation

## Русский

Engineering Preview 0.2.0 добавляет рабочее место **Optimal Operations** поверх уже принятой расчётной цепочки. Оно не заменяет и не переписывает физику P2/P3.

### Перед запуском

1. На целевом ПК должен быть локально установлен **Python 3.12**. Не переносите `.venv-preview` с другого компьютера: launcher создаёт окружение заново на каждой машине.
2. Запускайте `start-preview.bat` или `preview/start-preview-bootstrap.ps1` из распакованного пакета.
3. Встроенные Java 17/Orekit 13.1.7 и зафиксированный Orekit data package используются для DESIGN/VALIDATION расчётов.

### Optimal Operations 0.2

Рабочий поток двухэтапный:

1. **Foundation + screening**: явно выбрать DSST DESIGN ScenarioConfig и numerical VALIDATION ScenarioConfig, затем вставить полный `PreviewOptimalOperationsStudyProfile` JSON. Preview не подставляет control/search/robustness числа.
2. После получения screening candidates явно выбрать candidate.
3. **Authority + robustness + decision**: выбрать robustness campaign config, явно задать hybrid validation output step, screening bracket padding и полный `PreviewOperationalDecisionPolicy` JSON.
4. Рекомендация показывается только из persisted decision evidence. UI не рассчитывает Pareto, риск, расход топлива или lifetime самостоятельно.

### Семантика доверия

- Orekit DSST DESIGN — **screening only**.
- Orekit numerical VALIDATION — **authority**.
- Screening candidate не становится operationally credible от выбора в UI.
- Hard constraints нельзя компенсировать весами soft objectives.
- `Δu = M + ω` — прямая средняя фазовая координата оператора и не равна D'Amico `delta_lambda`.
- Недоступные robustness/lifetime значения не трактуются как ноль.

### Что фиксировать в отзыве

Используйте `preview/EXPERT_FEEDBACK.md`. Для каждого замечания укажите build/source SHA из `preview-manifest.json`, ScenarioConfig, study profile, decision policy, run artifact names и observed/expected behavior.

## English

Engineering Preview 0.2.0 adds the **Optimal Operations** workspace on top of the accepted P2/P3 computational chain. It does not replace or reimplement propagation/control physics.

### Before launch

1. The target PC must have **Python 3.12** installed locally. Never copy `.venv-preview` from another PC; the launcher creates a fresh environment on each target machine.
2. Launch `start-preview.bat` or `preview/start-preview-bootstrap.ps1` from the extracted package.
3. Bundled Java 17/Orekit 13.1.7 and pinned Orekit data are used for DESIGN/VALIDATION calculations.

### Optimal Operations 0.2

The operator workflow has two explicit stages:

1. **Foundation + screening**: explicitly select the DSST DESIGN and numerical VALIDATION ScenarioConfig files, then paste the complete `PreviewOptimalOperationsStudyProfile` JSON. Preview injects no control/search/robustness numerical defaults.
2. Explicitly select one persisted screening candidate.
3. **Authority + robustness + decision**: select the robustness campaign config and explicitly supply hybrid validation output step, screening bracket padding, and the complete `PreviewOperationalDecisionPolicy` JSON.
4. Recommendation is displayed only from persisted decision evidence. The UI never recomputes Pareto, risk, fuel or lifetime.

### Trust semantics

- Orekit DSST DESIGN is **screening only**.
- Orekit numerical VALIDATION is **authority**.
- Selecting a screening candidate in the UI does not make it operationally credible.
- Hard constraints cannot be weighted away by soft objectives.
- `Δu = M + ω` is the direct operator mean-phase coordinate and is distinct from D'Amico `delta_lambda`.
- Unavailable robustness/lifetime values are never treated as zero.

### Feedback evidence

Use `preview/EXPERT_FEEDBACK.md`. Include the build/source SHA from `preview-manifest.json`, ScenarioConfig, study profile, decision policy, relevant artifact names, and observed versus expected behavior.
