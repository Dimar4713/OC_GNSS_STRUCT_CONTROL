# Galileo GSC CI expectations

Required gates for merge:

- `ci`
- `preview-package-compat`
- `preview-0.2-package`

The feature must remain fail-closed when GSC network access is unavailable. Offline XML parsing is covered independently from live network availability.
