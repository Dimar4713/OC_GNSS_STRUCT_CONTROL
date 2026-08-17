# AIMETON project method applied to constellation-control

The repository is managed as an evolving engineering knowledge object: architecture, source, decisions, tests, evidence and backlog stay linked.

## Layers
- Mission issue defines product outcome and non-negotiable invariants.
- P0/P1 issues isolate executable work packages and acceptance evidence.
- ADRs freeze consequential technical decisions and their consequences.
- Scenario + manifest make computational claims reproducible.
- CI is an evidence gate, not decoration.
- Roadmap keeps the next fidelity level visible so a local MVP success does not terminate the mission.

## Three-angle check
A material result should eventually survive three independent views: analytical/semianalytical physics, numerical high-fidelity propagation, and statistical/Monte-Carlo robustness. Agreement with only one implementation is not sufficient proof of correctness.

## Safe evolution
Working behaviour is preserved unless there is a stated reason, a bounded change and regression evidence. Physical semantics (mean definition, frame, epoch, force model, time scale, units) are treated as API contracts.
