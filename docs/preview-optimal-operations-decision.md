# Engineering Preview 0.2 — Robustness / Pareto / Decision Contract

## Purpose
This stage turns already-authoritative strategy evaluations into a decision study. It does not create a Monte Carlo engine, Pareto algorithm or operational threshold. It composes the accepted robustness binding and `OperationalStrategyStudy` contracts.

## Explicit decision policy
Robustness probability limits and probability objectives are supplied through `PreviewOperationalDecisionPolicy`. Preview has no default risk threshold and no default recommendation strategy.

The decision policy explicitly contains:
- `recommendation_strategy_id`;
- `robustness_required`;
- `violation_probability_limits`;
- `violation_probability_objectives`.

## Paired robustness identity
All compared strategies must carry the exact same `CommonSampleSetIdentity`. Strategy ids must exactly cover the three P2 baselines plus the selected optimized candidate. Campaign id and sampling-model SHA-256 must match the preflighted robustness declaration.

`OperationalStudyIdentity.uncertainty_model_id` must equal the accepted robustness binding identity `robustness:<sampling_model_sha256>`.

Failed or missing realizations retain the accepted conservative semantics: they count as violations and are never interpreted as zero risk.

## Binding
Each strategy is passed through `bind_operational_robustness()`. Explicit probability limits become signed hard margins `limit - observed`; explicitly requested probability objectives become minimization objectives.

Authority backend and force-model fingerprint from completed robustness realizations must match the operational evaluation.

## Credible Pareto and recommendation
The study is assembled by the accepted `assemble_optimal_operations_study()` contract and Pareto membership is computed by `credible_pareto_strategy_ids()`.

Hard-constraint failures are excluded from credible Pareto but remain present in study evidence. Screening-only, awaiting-validation and authority-rejected candidates cannot be operationally credible.

When robustness is required for recommendation, the selected strategy must have complete robustness evidence. The recommendation must be operationally credible and belong to the credible Pareto set.

## Persistence
Decision artifacts are:
- `operational_study.json`;
- `paired_robustness.json`;
- `operational_decision.json`;
- `decision_manifest.json`.

The manifest retains preflight SHA, screening evidence SHA, authority selection SHA, common campaign/sample identity, credible Pareto ids, recommendation id and decision evidence SHA.
