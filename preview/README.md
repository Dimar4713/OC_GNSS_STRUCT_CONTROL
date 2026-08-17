# Engineering Preview Python 0.1

This directory is the handoff boundary for the first expert-facing Python preview of OC GNSS STRUCT CONTROL.

## Windows 10 quick start

1. Install Python 3.12 if it is not already available. No administrator rights are required for a per-user Python installation.
2. From the repository root run `start-preview.bat`.
3. The launcher creates `.venv-preview`, installs the reviewed runtime versions from `preview/requirements-preview.lock`, and starts the local UI on `http://127.0.0.1:8765`.
4. Select a scenario, inspect the authority banner and Expert/YAML view, then launch the calculation.
5. After completion use **Open engineering report** to inspect retained evidence.

The Preview binds to localhost by default. It does not expose a network service unless the operator explicitly changes the launcher behavior.

## High-fidelity authority

Screening can run with the Python runtime alone. Design and Validation are intentionally fail-closed and require the authoritative Orekit sidecar.

The launcher reads, rather than duplicates, the reviewed authority identity from:

- `sidecar/orekit-service/orekit-data-revision.txt`;
- `sidecar/orekit-service/orekit-data-sha256.txt`.

For high fidelity provide:

- `preview/runtime/orekit-service.jar` (release bundles will place the reviewed sidecar here), and
- `preview/runtime/orekit-data/`, or set `OREKIT_DATA_PATH` to the reviewed data directory.

Before starting Java, the launcher recomputes the physical orekit-data fingerprint using `scripts/fingerprint_orekit_data.py`. A mismatch stops startup. After Java starts, `/healthz` must report `status=ok`, `backend=orekit`, and the same physical SHA-256 before the UI can present the authority as ready.

If Java, JAR, or reviewed data are unavailable, the UI still starts for Screening while Design/Validation show **NOT READY**. There is no synthetic fallback for a high-fidelity request.

## Workspace

- `scenarios/` — validated scenario inputs. The Preview does not invent operational constellation constants.
- `preview/results/` — run outputs created through the UI.
- `preview/runtime/` — local/release high-fidelity runtime material; ignored by Git except for its boundary marker.
- `preview/EXPERT_FEEDBACK.md` — structured feedback form.

## Physics rule visible to experts

Secular behavior is evaluated from force-model-consistent mean elements. Instantaneous osculating semi-major axis is not a secular-drift optimisation/control criterion. Cartesian states are used for physical distance, navigation geometry and ground-track evidence.

## Current Preview boundary

This is deliberately an engineering preview, not the final Windows product. It exposes the accepted computational core with a thin local Web UI so experts can challenge scenario inputs, terminology, reports, authority semantics and workflow before the final packaged UI is frozen.
