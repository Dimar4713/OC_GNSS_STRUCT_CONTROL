from __future__ import annotations

import numpy as np

from constellation_control import __version__
from constellation_control.domain.models import OsculatingState, PropagationRequest, PropagationResult
from constellation_control.dynamics.j2 import first_order_j2_rates
from constellation_control.dynamics.orbits import ClassicalElements, classical_to_mean, mean_to_cartesian, mean_to_classical


class SyntheticMeanPropagator:
    """Deterministic screening backend. It is never valid as a high-fidelity validation backend."""

    def propagate(self, request: PropagationRequest) -> PropagationResult:
        if request.force_model.mode.value != "screening":
            raise ValueError("SyntheticMeanPropagator is restricted to screening mode")
        count = int(np.floor(request.duration_s / request.output_step_s)) + 1
        times = np.linspace(0.0, request.output_step_s * (count - 1), count)
        if times[-1] < request.duration_s:
            times = np.append(times, request.duration_s)

        mean_orbits = {}
        cartesian_states = {}
        for sat in request.satellites:
            initial = mean_to_classical(sat.mean_orbit)
            rates = first_order_j2_rates(initial, request.force_model)
            sat_mean = []
            sat_cart = []
            for time_s in times:
                propagated = ClassicalElements(
                    a_m=initial.a_m,
                    e=initial.e,
                    i_rad=initial.i_rad,
                    raan_rad=initial.raan_rad + rates.raan_rad_s * time_s,
                    argp_rad=initial.argp_rad + rates.argp_rad_s * time_s,
                    mean_anomaly_rad=initial.mean_anomaly_rad + rates.mean_anomaly_rad_s * time_s,
                )
                mean = classical_to_mean(propagated, sat.mean_orbit.definition)
                r_m, v_m_s = mean_to_cartesian(propagated, request.force_model.mu_m3_s2)
                sat_mean.append(mean)
                sat_cart.append(
                    OsculatingState(
                        epoch_s=float(time_s),
                        r_m=tuple(float(value) for value in r_m),
                        v_m_s=tuple(float(value) for value in v_m_s),
                    )
                )
            mean_orbits[sat.satellite_id] = tuple(sat_mean)
            cartesian_states[sat.satellite_id] = tuple(sat_cart)

        return PropagationResult(
            backend="synthetic-j2-screening",
            backend_version=__version__,
            force_model_fingerprint=request.force_model.fingerprint(),
            times_s=tuple(float(value) for value in times),
            mean_orbits=mean_orbits,
            cartesian_states=cartesian_states,
        )
