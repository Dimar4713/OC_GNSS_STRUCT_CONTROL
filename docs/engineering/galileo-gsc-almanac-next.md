# Galileo GSC next authority step

Before Galileo almanac records may create runnable `ScenarioConfig` objects, implement and review:

1. full Galileo System Time week resolution from modulo-4 `wna` using an explicit reference epoch;
2. Galileo almanac analytical propagation / state conversion through an authoritative Orekit path;
3. osculating state to project mean-orbit conversion where required;
4. lineage preservation from GSC XML URL/filename/SHA-256 to each derived spacecraft state;
5. numerical replay acceptance and physical-consistency diagnostics.
