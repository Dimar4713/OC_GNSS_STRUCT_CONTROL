from __future__ import annotations

from math import cos, isfinite, sin

from constellation_control.domain.models import MeanOrbit
from constellation_control.dynamics.orbits import mean_to_classical, wrap_pi
from constellation_control.mean_elements.roe import RelativeOrbitalElements

_EQUATORIAL_SIN_I_MIN = 1.0e-8


def delta_u_from_damico_roe(reference: MeanOrbit, relative: RelativeOrbitalElements) -> float:
    """Recover operator mean-phase difference Δu from D'Amico ROE.

    D'Amico uses
        delta_lambda = Δu + cos(i_ref) * ΔOmega
        delta_iy     = sin(i_ref) * ΔOmega

    so, away from the equatorial singularity,
        Δu = delta_lambda - cot(i_ref) * delta_iy.
    """

    ref = mean_to_classical(reference)
    sin_i = sin(ref.i_rad)
    if abs(sin_i) < _EQUATORIAL_SIN_I_MIN:
        raise ValueError("mean-phase/ROE mapping is ill-conditioned near equatorial inclination")
    return wrap_pi(relative.delta_lambda_rad - (cos(ref.i_rad) / sin_i) * relative.delta_iy)


def roe_target_for_delta_u(
    reference: MeanOrbit,
    current: RelativeOrbitalElements,
    target_delta_u_rad: float,
) -> RelativeOrbitalElements:
    """Build a phase-only ROE target while preserving all non-phase coordinates.

    The policy target is expressed in operator mean phase Δu, while the MPC state
    uses D'Amico delta_lambda. This adapter preserves the current nodal offset
    (`delta_iy`) and all other current ROE coordinates, changing only the
    D'Amico delta_lambda component required to represent the requested Δu.
    """

    target_delta_u = float(target_delta_u_rad)
    if not isfinite(target_delta_u):
        raise ValueError("target_delta_u_rad must be finite")

    ref = mean_to_classical(reference)
    sin_i = sin(ref.i_rad)
    if abs(sin_i) < _EQUATORIAL_SIN_I_MIN:
        raise ValueError("mean-phase/ROE mapping is ill-conditioned near equatorial inclination")

    target_delta_lambda = wrap_pi(target_delta_u + (cos(ref.i_rad) / sin_i) * current.delta_iy)
    return RelativeOrbitalElements(
        delta_a=current.delta_a,
        delta_lambda_rad=target_delta_lambda,
        delta_ex=current.delta_ex,
        delta_ey=current.delta_ey,
        delta_ix=current.delta_ix,
        delta_iy=current.delta_iy,
    )
