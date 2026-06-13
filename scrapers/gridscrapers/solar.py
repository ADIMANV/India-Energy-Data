"""Clear-sky solar shaping for intra-day fuel-mix estimation.

weight(zone, t) is a dimensionless multiplier on a state's daily-average
solar MW: 0 at night, peaking near local solar noon, normalized so the
daily mean is 1 (energy-preserving). Geometry only — no clouds; June haze
and monsoon make real output flatter, which the conventional-residual step
absorbs (docs/METHODOLOGY.md).
"""

import math
from datetime import datetime, timedelta

# state centroids (lat, lon) — approximate, good enough for solar geometry
STATE_CENTROIDS: dict[str, tuple[float, float]] = {
    "IN-AP": (15.9, 79.7), "IN-AR": (28.2, 94.7), "IN-AS": (26.2, 92.9),
    "IN-BR": (25.1, 85.3), "IN-CH": (30.7, 76.8), "IN-CG": (21.3, 81.9),
    "IN-DL": (28.6, 77.1), "IN-GA": (15.4, 74.0), "IN-GJ": (22.3, 71.7),
    "IN-HR": (29.1, 76.1), "IN-HP": (31.8, 77.2), "IN-JK": (33.5, 75.0),
    "IN-JH": (23.6, 85.3), "IN-KA": (15.3, 75.7), "IN-KL": (10.5, 76.3),
    "IN-MP": (23.5, 78.3), "IN-MH": (19.6, 76.1), "IN-MN": (24.7, 93.9),
    "IN-ML": (25.5, 91.3), "IN-MZ": (23.3, 92.8), "IN-NL": (26.1, 94.5),
    "IN-OD": (20.5, 84.4), "IN-PY": (11.9, 79.8), "IN-PB": (31.0, 75.4),
    "IN-RJ": (26.6, 73.8), "IN-SK": (27.6, 88.5), "IN-TN": (11.0, 78.4),
    "IN-TS": (17.9, 79.6), "IN-TR": (23.7, 91.7), "IN-UP": (26.9, 80.9),
    "IN-UK": (30.1, 79.3), "IN-WB": (23.8, 87.9),
}


def _elevation_sin(lat_deg: float, lon_deg: float, t_ist: datetime) -> float:
    """sin(solar elevation); ≤0 means below horizon."""
    doy = t_ist.timetuple().tm_yday
    decl = math.radians(23.45) * math.sin(2 * math.pi * (284 + doy) / 365)
    # local solar time: IST is UTC+5:30 = 82.5°E reference meridian
    solar_hour = t_ist.hour + t_ist.minute / 60 + (lon_deg - 82.5) * 4 / 60
    hour_angle = math.radians(15 * (solar_hour - 12))
    lat = math.radians(lat_deg)
    return (math.sin(lat) * math.sin(decl)
            + math.cos(lat) * math.cos(decl) * math.cos(hour_angle))


def weight(zone: str, t_ist: datetime) -> float:
    """Energy-preserving clear-sky multiplier (daily mean = 1)."""
    if zone not in STATE_CENTROIDS:
        return 1.0
    lat, lon = STATE_CENTROIDS[zone]
    s = max(0.0, _elevation_sin(lat, lon, t_ist))
    if s == 0.0:
        return 0.0
    # daily mean of max(0, sin(elevation)) at 15-min resolution
    day0 = t_ist.replace(hour=0, minute=0, second=0, microsecond=0)
    total = sum(
        max(0.0, _elevation_sin(lat, lon, day0 + timedelta(minutes=15 * i)))
        for i in range(96)
    )
    mean = total / 96
    return s / mean if mean > 0 else 0.0
