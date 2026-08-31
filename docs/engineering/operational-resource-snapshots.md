# Operational resource snapshots

The packaged 0.2.4 development flow can export an immutable planned spacecraft resource-state snapshot after all maneuvers scheduled in a selected scenario.

The snapshot contains the parent `scenario_id`, exact parent config hash, scenario-horizon timestamp, final current mass and propellant for each spacecraft, and the complete maneuver resource ledger including Isp authority.

Snapshots are stored below `runs/state-snapshots/` and are deliberately **not** written into the scenario catalog. They are not `ScenarioConfig` objects and do not advance orbital epoch or orbital state. Treating a post-maneuver fuel state as a new runnable orbital scenario while retaining the parent's orbital epoch would mix incompatible state times.

A future propagated-state derivation may create a runnable child scenario only when the final orbital state, epoch/time scale/frame, mean-element authority and operational resource state are advanced together.
