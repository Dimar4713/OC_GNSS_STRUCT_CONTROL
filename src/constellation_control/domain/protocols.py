from __future__ import annotations

from typing import Protocol

import numpy as np

from constellation_control.domain.models import ManeuverPlan, PropagationRequest, PropagationResult


class Propagator(Protocol):
    def propagate(self, request: PropagationRequest) -> PropagationResult: ...


class LinearizationProvider(Protocol):
    def linearize(self, request: PropagationRequest, times_s: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]: ...


class NavigationGeometryProvider(Protocol):
    def pdop(self, time_s: float, satellite_ids: tuple[str, ...]) -> float | None: ...


class PlanSafetyValidator(Protocol):
    def validate(self, plan: ManeuverPlan) -> bool: ...
