# Engineering Preview 0.2.3 — инженерное тестирование / Engineering evaluation

## Русский

Engineering Preview 0.2.3 — стабилизационная сборка поверх консолидированной 0.2.2 после реального запуска на Windows, выявившего повторный отказ Orekit sidecar на clean-PC runtime path.

### Главное изменение 0.2.3
Исправлен класс регрессий, который уже устранялся в 0.2.1, но не был полностью закрыт release-gate:
- bootstrap по-прежнему экспортирует pinned `OREKIT_DATA_REVISION`;
- **реальный `preview/start-preview.ps1` теперь независимо повторно экспортирует тот же reviewed revision**, поэтому прямой запуск launcher и будущие изменения bootstrap не могут вернуть `unversioned`;
- перед запуском на `127.0.0.1:8081` определяется владелец порта;
- если это распознанный старый Java `orekit-service.jar`, он завершается как stale sidecar перед чистым стартом;
- посторонний процесс на 8081 Preview автоматически не завершает;
- health gate дополнительно проверяет Orekit `13.1.7` вместе с pinned revision и physical SHA;
- окно старта sidecar увеличено до 30 секунд;
- при отказе в консоль выводятся фактически полученные version/revision/SHA и хвост stderr.

Release-gate 0.2.3 теперь запускает **реальный упакованный ZIP на Windows**. Перед этим CI намеренно поднимает stale sidecar с `orekit_data_revision=unversioned` на порту 8081. Пакет принимается только если `start-preview.bat` сам устраняет stale sidecar, запускает новый Orekit 13.1.7 с правильными revision/SHA и поднимает Preview `/health = 0.2.3`.

### Сохранённый функционал 0.2.2
- полный ScenarioConfig YAML editor с validation и save-as-new;
- P0 engineering geometry and mean-element semantics;
- P1 relative operations, long horizons and reporting;
- P2 closed-loop numerical maneuver authority, repeated campaign, resources/lifetime, checkpoint/resume/safe-stop;
- Design workflow;
- Robustness workflow;
- P3 Optimal Operations: DSST screening, hybrid numerical authority, optimized long-horizon campaign, paired robustness, credible Pareto and explicit recommendation policy.

Существующие/эталонные YAML не перезаписываются.

### Authority
- Orekit DSST DESIGN = screening/design evidence only.
- Orekit numerical VALIDATION = operational computation authority.
- Screening candidate не может стать credible только действием UI.
- High-fidelity контуры fail-closed.
- Hard constraints не компенсируются soft-objective weights.

### Идентификация пакета
Ожидаемые признаки:
- launcher/UI/health: `0.2.3`;
- Python package: `constellation-control 0.2.3`;
- ZIP/artifact: `engineering-preview-python-0.2.3-win10`;
- manifest: `Engineering Preview Python 0.2.3`;
- exact source SHA указан в `preview-manifest.json`;
- bundled Orekit: 13.1.7 с pinned data revision/SHA;
- manifest содержит clean-Windows sidecar invariant.

Для инженерного отзыва используйте `preview/EXPERT_FEEDBACK.md` и указывайте source SHA, сценарий, run/study id, изменённые входы и observed/expected behavior.

---

## English

Engineering Preview 0.2.3 is a stabilization build on top of consolidated 0.2.2 after a real Windows launch exposed another failure in the clean-PC Orekit-sidecar startup path.

### Main 0.2.3 change
The release now closes the regression class that was first addressed in 0.2.1 but was not fully covered by the release gate:
- bootstrap still exports pinned `OREKIT_DATA_REVISION`;
- **the real `preview/start-preview.ps1` independently reasserts that reviewed revision**, so direct launcher execution or future bootstrap changes cannot silently return to `unversioned`;
- the owner of `127.0.0.1:8081` is inspected before startup;
- a recognized stale Java `orekit-service.jar` is stopped before a clean launch;
- unrelated processes on port 8081 are never terminated automatically;
- the health gate validates Orekit `13.1.7` together with pinned revision and physical SHA;
- sidecar startup allowance is increased to 30 seconds;
- failures print actual version/revision/SHA and the stderr tail directly in the console.

The 0.2.3 release gate now runs the **real packaged ZIP on Windows**. CI deliberately seeds an old sidecar with `orekit_data_revision=unversioned` on port 8081 first. The package passes only if `start-preview.bat` removes that stale sidecar, starts Orekit 13.1.7 with the reviewed revision/SHA and exposes Preview `/health = 0.2.3`.

### Preserved 0.2.2 functionality
- complete ScenarioConfig YAML editor with validation and save-as-new;
- P0 engineering geometry and mean-element semantics;
- P1 relative operations, long horizons and reporting;
- P2 closed-loop numerical maneuver authority, repeated campaigns, resource/lifetime evidence, checkpoint/resume/safe-stop;
- Design workflow;
- Robustness workflow;
- P3 Optimal Operations with DSST screening, hybrid numerical authority, optimized long-horizon campaign, paired robustness, credible Pareto and explicit recommendation policy.

Existing/canonical YAML files remain protected from overwrite.

### Authority
- Orekit DSST DESIGN is screening/design evidence only.
- Orekit numerical VALIDATION is operational computation authority.
- UI actions cannot promote a screening candidate to credibility.
- High-fidelity contours remain fail-closed.
- Hard constraints cannot be weighted away by soft objectives.

### Package identity
Expected identity:
- launcher/UI/health: `0.2.3`;
- Python package: `constellation-control 0.2.3`;
- ZIP/artifact: `engineering-preview-python-0.2.3-win10`;
- manifest: `Engineering Preview Python 0.2.3`;
- exact source SHA in `preview-manifest.json`;
- bundled Orekit 13.1.7 with pinned data revision/SHA;
- manifest contains the clean-Windows sidecar invariant.

Use `preview/EXPERT_FEEDBACK.md` for engineering feedback and include source SHA, scenario, run/study id, modified inputs, and observed versus expected behavior.
