from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol

import numpy as np

from constellation_control.domain.models import ManeuverPlan, PropagationRequest, PropagationResult
from constellation_control.domain.navigation import DopMetrics, NavigationSiteConfig


class Propagator(Protocol):
    def propagate(self, request: PropagationRequest) -> PropagationResult: ...


class LinearizationProvider(Protocol):
    def linearize(self, request: PropagationRequest, times_s: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]: ...


class NavigationGeometryProvider(Protocol):
    def evaluate(
        self,
        satellite_inertial_positions_m: Mapping[str, Sequence[float]],
        *,
        time_s: float,
        site: NavigationSiteConfig,
    ) -> DopMetrics: ...


class PlanSafetyValidator(Protocol):
    def validate(self, plan: ManeuverPlan) -> bool: ...
