from __future__ import annotations

from dataclasses import dataclass
from math import atan2, cos, pi, sin, sqrt, tan

import numpy as np

from constellation_control.domain.models import MeanElementDefinition, MeanOrbit


@dataclass(frozen=True)
class ClassicalElements:
    a_m: float
    e: float
    i_rad: float
    raan_rad: float
    argp_rad: float
    mean_anomaly_rad: float


def wrap_pi(angle: float) -> float:
    return (angle + pi) % (2.0 * pi) - pi


def mean_to_classical(orbit: MeanOrbit) -> ClassicalElements:
    e = float(np.hypot(orbit.ex, orbit.ey))
    lon_peri = atan2(orbit.ey, orbit.ex) if e > 1e-15 else 0.0
    tan_i2 = float(np.hypot(orbit.ix, orbit.iy))
    i_rad = 2.0 * atan2(tan_i2, 1.0)
    raan = atan2(orbit.iy, orbit.ix) if tan_i2 > 1e-15 else 0.0
    argp = wrap_pi(lon_peri - raan)
    mean_anomaly = wrap_pi(orbit.lambda_rad - lon_peri)
    return ClassicalElements(orbit.a_m, e, i_rad, raan, argp, mean_anomaly)


def classical_to_mean(elements: ClassicalElements, definition: MeanElementDefinition) -> MeanOrbit:
    lon_peri = elements.raan_rad + elements.argp_rad
    t = tan(elements.i_rad / 2.0)
    return MeanOrbit(
        a_m=elements.a_m,
        ex=elements.e * cos(lon_peri),
        ey=elements.e * sin(lon_peri),
        ix=t * cos(elements.raan_rad),
        iy=t * sin(elements.raan_rad),
        lambda_rad=wrap_pi(elements.mean_anomaly_rad + lon_peri),
        definition=definition,
    )


def solve_kepler(mean_anomaly_rad: float, eccentricity: float, iterations: int = 12) -> float:
    eccentric_anomaly = mean_anomaly_rad
    for _ in range(iterations):
        f = eccentric_anomaly - eccentricity * sin(eccentric_anomaly) - mean_anomaly_rad
        fp = 1.0 - eccentricity * cos(eccentric_anomaly)
        eccentric_anomaly -= f / fp
    return eccentric_anomaly


def mean_to_cartesian(elements: ClassicalElements, mu_m3_s2: float) -> tuple[np.ndarray, np.ndarray]:
    a = elements.a_m
    e = elements.e
    eccentric_anomaly = solve_kepler(elements.mean_anomaly_rad, e)
    x_p = a * (cos(eccentric_anomaly) - e)
    y_p = a * sqrt(1.0 - e * e) * sin(eccentric_anomaly)
    n = sqrt(mu_m3_s2 / a**3)
    denom = 1.0 - e * cos(eccentric_anomaly)
    vx_p = -a * n * sin(eccentric_anomaly) / denom
    vy_p = a * n * sqrt(1.0 - e * e) * cos(eccentric_anomaly) / denom

    c_o, s_o = cos(elements.raan_rad), sin(elements.raan_rad)
    c_i, s_i = cos(elements.i_rad), sin(elements.i_rad)
    c_w, s_w = cos(elements.argp_rad), sin(elements.argp_rad)
    rotation = np.array(
        [
            [c_o * c_w - s_o * s_w * c_i, -c_o * s_w - s_o * c_w * c_i, s_o * s_i],
            [s_o * c_w + c_o * s_w * c_i, -s_o * s_w + c_o * c_w * c_i, -c_o * s_i],
            [s_w * s_i, c_w * s_i, c_i],
        ]
    )
    return rotation @ np.array([x_p, y_p, 0.0]), rotation @ np.array([vx_p, vy_p, 0.0])


def semi_major_axis_from_state(r_m: np.ndarray, v_m_s: np.ndarray, mu_m3_s2: float) -> float:
    energy = 0.5 * float(v_m_s @ v_m_s) - mu_m3_s2 / float(np.linalg.norm(r_m))
    return -mu_m3_s2 / (2.0 * energy)


def apply_tangential_impulse(r_m: np.ndarray, v_m_s: np.ndarray, dv_t_m_s: float) -> np.ndarray:
    r_hat = r_m / np.linalg.norm(r_m)
    h_hat = np.cross(r_m, v_m_s)
    h_hat = h_hat / np.linalg.norm(h_hat)
    t_hat = np.cross(h_hat, r_hat)
    return v_m_s + dv_t_m_s * t_hat
