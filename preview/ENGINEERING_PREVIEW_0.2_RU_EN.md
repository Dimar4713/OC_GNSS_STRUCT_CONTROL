# Engineering Preview 0.2.2 — инженерное тестирование / Engineering evaluation

## Русский

Engineering Preview 0.2.2 — первая консолидированная сборка после аудита веток и возврата всей принятой линии P0–P3 в canonical `main`.

### Главное изменение 0.2.2
В операторскую оболочку добавлен **полный ScenarioConfig YAML editor**. Теперь инженер может менять не только propagation horizon, но и `output_step_s`, force model, integrator, constraints, Monte Carlo, параметры орбитальной группировки/КА, navigation sites и maneuvers.

Изменённый YAML:
1. проходит полную `ScenarioConfig` validation;
2. получает новый normalized view и force-model fingerprint;
3. сохраняется только под новым именем;
4. сразу становится доступен для запуска.

Существующие/эталонные YAML не перезаписываются.

### Состав консолидированной версии
- P0 engineering geometry and mean-element semantics;
- P1 relative operations, long horizons and reporting;
- P2 closed-loop numerical maneuver authority, repeated campaign, resources/lifetime, checkpoint/resume/safe-stop;
- Design workflow;
- Robustness workflow;
- P3 Optimal Operations: DSST screening, hybrid numerical authority, optimized long-horizon campaign, paired robustness, credible Pareto and explicit recommendation policy;
- clean-Windows Orekit-data revision bootstrap fix from the 0.2.1 stabilization line.

### Authority
- Orekit DSST DESIGN = screening/design evidence only.
- Orekit numerical VALIDATION = operational computation authority.
- Screening candidate не может стать credible только действием UI.
- High-fidelity контуры fail-closed.
- Hard constraints не компенсируются soft-objective weights.

### Идентификация пакета
Ожидаемые признаки:
- UI/health: `0.2.2`;
- ZIP/artifact: `engineering-preview-python-0.2.2-win10`;
- manifest: `Engineering Preview Python 0.2.2`;
- exact source SHA указан в `preview-manifest.json`;
- bundled Orekit: 13.1.7 с pinned data revision/SHA.

Для инженерного отзыва используйте `preview/EXPERT_FEEDBACK.md` и указывайте source SHA, сценарий, run/study id, изменённые входы и observed/expected behavior.

---

## English

Engineering Preview 0.2.2 is the first consolidated build after the branch audit restored the complete accepted P0–P3 line to canonical `main`.

### Main 0.2.2 change
The operator shell now includes a **complete ScenarioConfig YAML editor**. Engineers can modify not only propagation horizon but also `output_step_s`, force model, integrator, constraints, Monte Carlo, constellation/spacecraft parameters, navigation sites and maneuvers.

Edited YAML:
1. passes full `ScenarioConfig` validation;
2. exposes the normalized model and resulting force-model fingerprint;
3. is saved only under a new file name;
4. becomes immediately selectable for execution.

Existing/canonical YAML files are never overwritten.

### Consolidated functionality
- P0 engineering geometry and mean-element semantics;
- P1 relative operations, long horizons and reporting;
- P2 closed-loop numerical maneuver authority, repeated campaigns, resource/lifetime evidence, checkpoint/resume/safe-stop;
- Design workflow;
- Robustness workflow;
- P3 Optimal Operations with DSST screening, hybrid numerical authority, optimized long-horizon campaign, paired robustness, credible Pareto and explicit recommendation policy;
- clean-Windows Orekit-data revision bootstrap fix from the 0.2.1 stabilization line.

### Authority
- Orekit DSST DESIGN is screening/design evidence only.
- Orekit numerical VALIDATION is operational computation authority.
- UI actions cannot promote a screening candidate to credibility.
- High-fidelity contours remain fail-closed.
- Hard constraints cannot be weighted away by soft objectives.

### Package identity
Expected identity:
- UI/health: `0.2.2`;
- ZIP/artifact: `engineering-preview-python-0.2.2-win10`;
- manifest: `Engineering Preview Python 0.2.2`;
- exact source SHA in `preview-manifest.json`;
- bundled Orekit 13.1.7 with pinned data revision/SHA.

Use `preview/EXPERT_FEEDBACK.md` for engineering feedback and include source SHA, scenario, run/study id, modified inputs, and observed versus expected behavior.
