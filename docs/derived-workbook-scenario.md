# Derived scenario from spacecraft workbook

This flow applies a validated XLS/XLSX spacecraft-state workbook as a **new derived scenario**. The selected source YAML remains immutable.

## Required operator inputs

- source scenario selected in the packaged Preview UI;
- `.xls` / `.xlsx` workbook;
- a new YAML file name;
- a new `scenario_id` distinct from the parent.

## Provenance written into the child scenario

`digital_twin.lineage` records:

- `parent_scenario_id`;
- `parent_config_hash`;
- `transformation: import`;
- `random_seed: null` for deterministic workbook import.

The child configuration contains imported `spacecraft_states` and groups. Existing parent perturbation rules are preserved; the import operation does not invent new perturbations.

## Safety / acceptance rules

- parent scenario file is never overwritten;
- target filename must be a plain `.yaml` / `.yml` name and must not already exist;
- child `scenario_id` must be non-empty and different from the parent id;
- workbook is revalidated against the parent scenario at apply time (preview is not trusted as authorization state);
- unknown spacecraft/group membership fails closed;
- source and child config hashes are returned after save.

The workbook adapter remains a convenience layer; no numerical-authority, force-model, frame, time-scale, integrator, or propagation semantics are changed by this operation.
