# Galileo GSC implementation

Implementation files:

- `src/constellation_control/adapters/galileo_gsc_almanac.py`
- `src/constellation_control/preview/galileo_gsc_input.py`
- `tests/test_galileo_gsc_almanac.py`

Consolidated Preview integration is in `src/constellation_control/preview/consolidated_release_app.py`.

This phase provides reviewed source intake and normalization only. Runnable Galileo scenario promotion is intentionally deferred until full week resolution and the authoritative almanac-to-state path are reviewed and validated against Orekit/numerical authority.
