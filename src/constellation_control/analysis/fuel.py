from __future__ import annotations

from math import exp

G0_M_S2 = 9.80665


def propellant_used_kg(initial_mass_kg: float, delta_v_m_s: float, isp_s: float) -> float:
    if initial_mass_kg <= 0.0 or delta_v_m_s < 0.0 or isp_s <= 0.0:
        raise ValueError("mass and Isp must be positive and delta-v non-negative")
    return initial_mass_kg * (1.0 - exp(-delta_v_m_s / (G0_M_S2 * isp_s)))
