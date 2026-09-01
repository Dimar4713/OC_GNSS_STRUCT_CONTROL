from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from threading import Lock, Thread
from time import time
from typing import Callable, Generic, TypeVar
from uuid import uuid4

T = TypeVar("T")


@dataclass(frozen=True)
class ProgressSnapshot:
    job_id: str
    state: str
    phase: str
    percent: float
    scenario_name: str
    duration_s: float
    output_step_s: float
    point_index: int | None = None
    point_total: int | None = None
    satellite_id: str | None = None
    satellite_index: int | None = None
    satellite_total: int | None = None
    time_s: float | None = None
    epoch: str | None = None
    message: str | None = None
    error: str | None = None
    result: dict[str, object] | None = None
    created_at_unix_s: float = 0.0
    updated_at_unix_s: float = 0.0

    def payload(self) -> dict[str, object]:
        return asdict(self)


class PreviewRunJobManager(Generic[T]):
    """Thread-safe local job registry for non-blocking Preview execution.

    Workers receive a progress callback and return the final API-compatible result payload.
    Snapshots are immutable replacements so status readers never observe partially-mutated state.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._jobs: dict[str, ProgressSnapshot] = {}
        self._active_keys: dict[tuple[str, float, float], str] = {}

    def start(
        self,
        *,
        scenario_name: str,
        duration_s: float,
        output_step_s: float,
        worker: Callable[[Callable[..., None]], dict[str, object]],
    ) -> ProgressSnapshot:
        key = (scenario_name, float(duration_s), float(output_step_s))
        now = time()
        with self._lock:
            active_id = self._active_keys.get(key)
            if active_id is not None:
                active = self._jobs[active_id]
                if active.state in {"queued", "running"}:
                    return active
            job_id = str(uuid4())
            snapshot = ProgressSnapshot(
                job_id=job_id,
                state="queued",
                phase="queued",
                percent=0.0,
                scenario_name=scenario_name,
                duration_s=float(duration_s),
                output_step_s=float(output_step_s),
                created_at_unix_s=now,
                updated_at_unix_s=now,
            )
            self._jobs[job_id] = snapshot
            self._active_keys[key] = job_id

        def update(**changes: object) -> None:
            self.update(job_id, **changes)

        def execute() -> None:
            try:
                update(state="running", phase="propagation", percent=1.0, message="numerical propagation")
                result = worker(update)
                update(state="running", phase="artifacts", percent=99.0, message="finalizing artifacts")
                update(state="completed", phase="completed", percent=100.0, result=result, message="completed")
            except Exception as exc:  # noqa: BLE001 - boundary must retain exact failure text
                update(state="failed", phase="failed", error=str(exc), message=str(exc))
            finally:
                with self._lock:
                    if self._active_keys.get(key) == job_id:
                        self._active_keys.pop(key, None)

        Thread(target=execute, name=f"preview-run-{job_id[:8]}", daemon=True).start()
        return snapshot

    def update(self, job_id: str, **changes: object) -> ProgressSnapshot:
        with self._lock:
            current = self._jobs[job_id]
            requested_percent = float(changes.get("percent", current.percent))
            if requested_percent < current.percent:
                requested_percent = current.percent
            if requested_percent > 100.0:
                requested_percent = 100.0
            changes["percent"] = requested_percent
            changes["updated_at_unix_s"] = time()
            updated = replace(current, **changes)
            self._jobs[job_id] = updated
            return updated

    def get(self, job_id: str) -> ProgressSnapshot | None:
        with self._lock:
            return self._jobs.get(job_id)
