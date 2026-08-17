from __future__ import annotations

from dataclasses import dataclass
from math import cos, sin

from constellation_control.dynamics.orbits import mean_to_classical, wrap_pi
from constellation_control.domain.models import MeanOrbit


@dataclass(frozen=True)
class RelativeOrbitalElements:
    delta_a: float
    delta_lambda_rad: float
    delta_ex: float
    delta_ey: float
    delta_ix: float
    delta_iy: float


def damico_roe(reference: MeanOrbit, deputy: MeanOrbit) -> RelativeOrbitalElements:
    ref = mean_to_classical(reference)
    dep = mean_to_classical(deputy)
    delta_raan = wrap_pi(dep.raan_rad - ref.raan_rad)
    delta_argp = wrap_pi(dep.argp_rad - ref.argp_rad)
    delta_m = wrap_pi(dep.mean_anomaly_rad - ref.mean_anomaly_rad)
    delta_lambda = wrap_pi(delta_m + delta_argp + cos(ref.i_rad) * delta_raan)
    return RelativeOrbitalElements(
        delta_a=(dep.a_m - ref.a_m) / ref.a_m,
        delta_lambda_rad=delta_lambda,
        delta_ex=dep.e * cos(dep.argp_rad) - ref.e * cos(ref.argp_rad),
        delta_ey=dep.e * sin(dep.argp_rad) - ref.e * sin(ref.argp_rad),
        delta_ix=dep.i_rad - ref.i_rad,
        delta_iy=sin(ref.i_rad) * delta_raan,
    )
