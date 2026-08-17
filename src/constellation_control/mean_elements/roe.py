from __future__ import annotations

from dataclasses import dataclass
from math import atan2, cos, hypot, sin

from constellation_control.domain.models import MeanOrbit
from constellation_control.dynamics.orbits import (
    ClassicalElements,
    classical_to_mean,
    mean_to_classical,
    wrap_pi,
)


@dataclass(frozen=True)
class RelativeOrbitalElements:
    delta_a: float
    delta_lambda_rad: float
    delta_ex: float
    delta_ey: float
    delta_ix: float
    delta_iy: float

    def as_tuple(self) -> tuple[float, float, float, float, float, float]:
        return (
            self.delta_a,
            self.delta_lambda_rad,
            self.delta_ex,
            self.delta_ey,
            self.delta_ix,
            self.delta_iy,
        )


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


def mean_from_damico_roe(reference: MeanOrbit, relative: RelativeOrbitalElements) -> MeanOrbit:
    """Construct a deputy mean orbit from D'Amico ROE using the reference definition.

    This is an inverse coordinate mapping for local design/control work. It is not
    an osculating conversion and therefore preserves the reference mean-element
    theory and force-model fingerprint.
    """

    ref = mean_to_classical(reference)
    sin_i = sin(ref.i_rad)
    if abs(sin_i) < 1.0e-8:
        raise ValueError("D'Amico delta_iy inversion is ill-conditioned near equatorial inclination")

    a_m = ref.a_m * (1.0 + relative.delta_a)
    if a_m <= 0.0:
        raise ValueError("ROE perturbation produced a non-positive semi-major axis")

    ex_abs = ref.e * cos(ref.argp_rad) + relative.delta_ex
    ey_abs = ref.e * sin(ref.argp_rad) + relative.delta_ey
    eccentricity = hypot(ex_abs, ey_abs)
    argp = ref.argp_rad if eccentricity < 1.0e-15 else atan2(ey_abs, ex_abs)

    inclination = ref.i_rad + relative.delta_ix
    delta_raan = relative.delta_iy / sin_i
    raan = ref.raan_rad + delta_raan
    delta_argp = wrap_pi(argp - ref.argp_rad)
    delta_m = relative.delta_lambda_rad - delta_argp - cos(ref.i_rad) * delta_raan
    mean_anomaly = ref.mean_anomaly_rad + delta_m

    deputy = ClassicalElements(
        a_m=a_m,
        e=eccentricity,
        i_rad=inclination,
        raan_rad=raan,
        argp_rad=argp,
        mean_anomaly_rad=mean_anomaly,
    )
    return classical_to_mean(deputy, reference.definition)
