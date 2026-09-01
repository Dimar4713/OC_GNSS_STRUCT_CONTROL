# Restored legacy GLONASS 24+6 source

The project primary source `АС_GLO 24+6.txt` was recovered from the project File Library and restored in normalized UTF-8 form as `data/legacy/glonass/AS_GLO_24plus6.txt`.

It contains the exact 30-row idealized constellation inventory used by the historical 24+6 work: satellites 1..24 plus additional satellites 25..30 inserted between pairs 1/2, 5/6, 10/11, 14/15, 19/20 and 23/24. All rows preserve the source columns `T_om`, `T_ob`, `e`, `i`, `L_om`, `Om`, `dt2`, `nl`, `dT`.

## Authority classification

This is a **legacy project source**, not a current broadcast GLONASS almanac and not `glonass_authority_v1`. It must not be silently promoted to modern GLONASS almanac authority.

The strict parser preserves and validates the source inventory but deliberately does not invent the historical transformation from legacy `T_om/L_om` fields into a current `ScenarioConfig` mean-orbit epoch. That transformation must be explicit and tested before a reconstructed runnable scenario is called source-derived.

For issue #171, this source is the correct lineage anchor for reproducing the historical GLONASS 24+6 calculation. Numerical acceptance still requires a completed authoritative Orekit VALIDATION run and retained drift evidence; restoring this file alone does not close #171.
