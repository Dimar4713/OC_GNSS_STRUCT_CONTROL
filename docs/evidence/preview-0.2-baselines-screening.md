# Preview 0.2 baseline + screening evidence contract

Issue: #103, parent #100.

This slice intentionally stops before hybrid authority validation and final recommendation.

Accepted routing:
1. explicit profile preflight;
2. three P2 baseline campaigns using accepted control code;
3. full-horizon Orekit numerical replay of exact accepted resource-ledger maneuvers for comparable trajectory hard margins;
4. accepted operational metrics reducer for P2 resource evidence;
5. accepted operational policy screening search using the exact explicit profile config;
6. screening candidates remain non-authoritative;
7. deterministic content-addressed JSON evidence; recommendation remains null.

Safety semantics:
- NO CONTROL retains zero-authority execution semantics but receives a separate zero-maneuver numerical outcome replay;
- hard-failing baselines remain authoritative observations and are not silently discarded;
- a controlled baseline that fails to cover the declared campaign horizon is rejected;
- unavailable annualized/lifetime objectives are rejected rather than assigned zero/infinity;
- screening Pareto is not credible Pareto;
- no robustness is fabricated in this slice.
