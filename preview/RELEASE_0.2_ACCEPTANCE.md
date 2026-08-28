# Engineering Preview 0.2.0 — release acceptance

Release issue: #109. Parent: #100.

Acceptance requires one exact PR head with all of the following GREEN:

- Ruff, mypy, full pytest;
- Java Orekit integration including DSST maneuver response;
- DSST design and numerical validation application paths;
- MPC numerical replay authority;
- robustness and design/top-K lineage regression;
- legacy Windows Preview regression (0.1.5 surfaces remain intact);
- Preview 0.2 Windows HTTP/UI smoke;
- `engineering-preview-python-0.2.0-win10` bundle, manifest and checksum.

Release invariants:

- screening never authority;
- no hidden control/search/robustness/decision numerical defaults;
- persisted foundation is reused rather than repeating search after candidate selection;
- recommendation is read from accepted decision evidence only;
- `.venv-preview` is created fresh on each target PC and must never be copied between computers;
- 0.1.5 remains a historical frozen engineering control build.
