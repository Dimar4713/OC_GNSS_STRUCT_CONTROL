# Engineering Preview 0.2 — Optimized Candidate Hybrid Authority

## Status
Authority slice under #100 / #105. This layer starts from persisted screening-only candidate evidence and may produce an authoritatively validated or authority-rejected optimized candidate. It does not execute robustness and cannot emit a final recommendation.

## Selection lineage
A candidate is selected only by exact `candidate_id` from one frozen `PreviewOptimalOperationsFoundationRun`. Selection persists both the foundation `preflight_sha256` and `screening_evidence_sha256`; both are checked again before validation and before final reduction. Infeasible or non-screening candidates fail closed.

## First optimized event
The first high-fidelity optimized trigger is never seeded from a screening state and is never represented as a fake post-maneuver transition. It is replayed numerically from the validated ScenarioConfig initial condition and receives a `StateAnchorKind.AUTHORITATIVE_REPLAY` anchor.

The accepted optimized trigger scanner is reused. Screening supplies only a bracket/hypothesis; `orekit-numerical*` replay decides whether the event is confirmed, shifted or absent.

## Correction authority
Confirmed/shifted events are routed through the accepted P2 numerical maneuver-authority path and retain its correction authority receipt, hard margins, replay backend and transition force-model lineage. Rejected/absent events remain explicit evidence and cannot become credible.

## Credibility reduction
`run_hybrid_strategy_validation()` is the only reducer that decides `authoritatively-validated-candidate`, `candidate-awaiting-validation` or `rejected-by-authority` for this slice. Preview does not set credibility directly.

## Operational outcome
`build_optimized_operational_evaluation()` is the only reducer that constructs the optimized operational evaluation. Screening objective scores are intentionally ignored. Final named objectives and operational metrics must come from `AuthoritativeOperationalOutcomeEvidence`.

## Persistence
The authority evidence writer stores:
- `optimized_candidate_selection.json`;
- `hybrid_authority.json`;
- `optimized_evaluation.json`;
- `authority_manifest.json`.

The manifest binds preflight SHA, screening evidence SHA, selection SHA, authority evidence SHA, resulting credibility state and high-fidelity validation id.

## Explicit boundary
This slice always persists:
- `robustness_available = false`;
- `recommendation_strategy_id = null`.

Paired robustness, credible Pareto assembly and final recommendation are a later child of #100.
