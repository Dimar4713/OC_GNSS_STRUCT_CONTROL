from __future__ import annotations

from itertools import combinations
from math import sqrt

from pydantic import BaseModel, ConfigDict

from constellation_control.analysis.relative_operations import mean_phase_rad
from constellation_control.domain.models import ConstraintConfig, PropagationResult
from constellation_control.dynamics.orbits import wrap_pi


class CampaignTrajectoryHardMargins(BaseModel):
    """Hard-margin reduction from one accepted propagation result.

    This reducer performs no propagation, interpolation, maneuver sizing, or
    authority decision. It only reduces states already returned by a propagator.
    """

    model_config = ConfigDict(frozen=True)

    phase_corridor_margin_rad: float
    minimum_fleet_distance_margin_m: float | None
    samples: int
    pair_distance_samples: int


def reduce_trajectory_hard_margins(
    result: PropagationResult,
    constraints: ConstraintConfig,
    *,
    reference_id: str,
    deputy_id: str,
) -> CampaignTrajectoryHardMargins:
    if result.force_model_fingerprint == "":
        raise ValueError("trajectory hard-margin evidence requires force-model fingerprint")
    times = result.times_s
    if not times:
        raise ValueError("trajectory hard-margin evidence requires at least one sample")
    if reference_id not in result.mean_orbits or deputy_id not in result.mean_orbits:
        raise ValueError("trajectory hard-margin evidence lacks reference/deputy mean histories")
    reference = result.mean_orbits[reference_id]
    deputy = result.mean_orbits[deputy_id]
    if len(reference) != len(times) or len(deputy) != len(times):
        raise ValueError("trajectory mean histories must match result time grid")

    phase_margin = min(
        constraints.phase_corridor_rad - abs(wrap_pi(mean_phase_rad(dep) - mean_phase_rad(ref)))
        for ref, dep in zip(reference, deputy, strict=True)
    )

    fleet_margin: float | None = None
    pair_samples = 0
    ids = sorted(result.cartesian_states)
    if len(ids) >= 2:
        for satellite_id in ids:
            if len(result.cartesian_states[satellite_id]) != len(times):
                raise ValueError("trajectory Cartesian histories must match result time grid")
        minimum_distance: float | None = None
        for left_id, right_id in combinations(ids, 2):
            left_history = result.cartesian_states[left_id]
            right_history = result.cartesian_states[right_id]
            for left, right in zip(left_history, right_history, strict=True):
                dx = left.r_m[0] - right.r_m[0]
                dy = left.r_m[1] - right.r_m[1]
                dz = left.r_m[2] - right.r_m[2]
                distance = sqrt(dx * dx + dy * dy + dz * dz)
                minimum_distance = distance if minimum_distance is None else min(minimum_distance, distance)
                pair_samples += 1
        if minimum_distance is not None:
            fleet_margin = minimum_distance - constraints.min_pair_distance_m

    return CampaignTrajectoryHardMargins(
        phase_corridor_margin_rad=float(phase_margin),
        minimum_fleet_distance_margin_m=None if fleet_margin is None else float(fleet_margin),
        samples=len(times),
        pair_distance_samples=pair_samples,
    )
