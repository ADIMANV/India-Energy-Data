"""India power-plant registry loader.

Source: WRI Global Power Plant Database (GPPD) CSV — powerplantmatching's
precompiled dataset contains no India plants (checked 2026-06-11, v0.8.1),
so GPPD is the primary source. Refresh procedure: docs/METHODOLOGY.md.

Usage:
    python -m gridscrapers.plants load [--csv /tmp/gppd.csv]

State attribution is point-in-polygon (ray casting) against the same
datameet states GeoJSON the frontend uses.
"""

import argparse
import csv
import json
import os
import sys
from pathlib import Path

import httpx
import psycopg

from .db import get_dsn
from .zones import NATIONAL  # noqa: F401  (zone vocabulary lives in zones.py)

GPPD_URL = (
    "https://raw.githubusercontent.com/wri/global-power-plant-database/"
    "master/output_database/global_power_plant_database.csv"
)


def _find_geojson() -> Path:
    """State boundaries, for assigning each plant's lat/lon to a zone.

    The repo-relative path only resolves in a source checkout — once the
    package is pip-installed (i.e. the deploy image) __file__ lives in
    site-packages and web/ isn't shipped. Check an explicit override and the
    image path too, or the loader silently has no boundaries to match against
    and every plant is dropped.
    """
    candidates = [
        Path(p) for p in (os.environ.get("GRID_GEOJSON_PATH"),) if p
    ] + [
        Path(__file__).parents[2] / "web/public/india_states.geojson",  # source checkout
        Path("/app/data/india_states.geojson"),                          # deploy image
    ]
    for c in candidates:
        if c.is_file():
            return c
    raise FileNotFoundError(
        "india_states.geojson not found. Set GRID_GEOJSON_PATH, or run from a "
        f"source checkout. Looked in: {', '.join(str(c) for c in candidates)}"
    )


GEOJSON_PATH = None  # resolved lazily by load_state_geoms so import never fails

FUEL_MAP = {
    "Coal": "coal", "Gas": "gas", "Oil": "oil", "Petcoke": "coal",
    "Hydro": "hydro", "Nuclear": "nuclear", "Solar": "solar", "Wind": "wind",
    "Biomass": "biomass", "Waste": "biomass", "Cogeneration": "other",
    "Storage": "other", "Other": "other", "Geothermal": "other", "Wave and Tidal": "other",
}

# datameet ST_NM -> zone (mirror of web/lib/zones.js)
NAME_TO_ZONE = {
    "Andhra Pradesh": "IN-AP", "Arunanchal Pradesh": "IN-AR", "Assam": "IN-AS",
    "Bihar": "IN-BR", "Chandigarh": "IN-CH", "Chhattisgarh": "IN-CG",
    "NCT of Delhi": "IN-DL", "Goa": "IN-GA", "Gujarat": "IN-GJ", "Haryana": "IN-HR",
    "Himachal Pradesh": "IN-HP", "Jammu & Kashmir": "IN-JK", "Jharkhand": "IN-JH",
    "Karnataka": "IN-KA", "Kerala": "IN-KL", "Madhya Pradesh": "IN-MP",
    "Maharashtra": "IN-MH", "Manipur": "IN-MN", "Meghalaya": "IN-ML",
    "Mizoram": "IN-MZ", "Nagaland": "IN-NL", "Odisha": "IN-OD",
    "Puducherry": "IN-PY", "Punjab": "IN-PB", "Rajasthan": "IN-RJ",
    "Sikkim": "IN-SK", "Tamil Nadu": "IN-TN", "Telangana": "IN-TS",
    "Tripura": "IN-TR", "Uttar Pradesh": "IN-UP", "Uttarakhand": "IN-UK",
    "West Bengal": "IN-WB",
}


def _point_in_ring(lon: float, lat: float, ring: list) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _point_in_geom(lon: float, lat: float, geom: dict) -> bool:
    polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
    for poly in polys:
        if _point_in_ring(lon, lat, poly[0]):  # outer ring only — holes negligible here
            return True
    return False


def load_state_geoms(path: Path | None = None) -> list[tuple[str, dict]]:
    path = path or _find_geojson()
    geo = json.loads(path.read_text())
    out = []
    for f in geo["features"]:
        zone = NAME_TO_ZONE.get(f["properties"]["ST_NM"])
        if zone:
            out.append((zone, f["geometry"]))
    return out


def state_for(lon: float | None, lat: float | None, geoms) -> str | None:
    if lon is None or lat is None:
        return None
    for zone, geom in geoms:
        if _point_in_geom(lon, lat, geom):
            return zone
    return None


def load(csv_path: str | None) -> int:
    if csv_path:
        text = Path(csv_path).read_text()
    else:
        print(f"downloading {GPPD_URL}", file=sys.stderr)
        text = httpx.get(GPPD_URL, timeout=120).raise_for_status().text

    geoms = load_state_geoms()
    rows = []
    for r in csv.DictReader(text.splitlines()):
        if r["country"] != "IND":
            continue
        lat = float(r["latitude"]) if r["latitude"] else None
        lon = float(r["longitude"]) if r["longitude"] else None
        rows.append((
            r["name"],
            FUEL_MAP.get(r["primary_fuel"], "other"),
            float(r["capacity_mw"]) if r["capacity_mw"] else None,
            lat, lon,
            state_for(lon, lat, geoms),
            "gppd",
            r["gppd_idnr"],
            (r.get("owner") or "").strip() or None,
            int(float(r["commissioning_year"])) if r.get("commissioning_year") else None,
        ))

    # Upsert on the source's own id rather than TRUNCATE + reinsert:
    # station_daily.plant_id references these rows, so a truncate fails once any
    # PSP data exists — and RESTART IDENTITY would renumber ids and repoint
    # existing references at the wrong plants. Keying on (source, source_id)
    # keeps ids stable across refreshes.
    with psycopg.connect(get_dsn()) as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO india_plants
                       (name, fuel, capacity_mw, lat, lon, state_zone, source,
                        source_id, owner, commissioning_year)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (source, source_id) WHERE source_id IS NOT NULL
                   DO UPDATE SET name = EXCLUDED.name,
                                 fuel = EXCLUDED.fuel,
                                 capacity_mw = EXCLUDED.capacity_mw,
                                 lat = EXCLUDED.lat,
                                 lon = EXCLUDED.lon,
                                 state_zone = EXCLUDED.state_zone,
                                 owner = EXCLUDED.owner,
                                 commissioning_year = EXCLUDED.commissioning_year,
                                 loaded_at = now()""",
                rows,
            )
        conn.commit()
    return len(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", choices=["load"])
    ap.add_argument("--csv", help="local GPPD csv (skips download)")
    args = ap.parse_args()
    n = load(args.csv)
    print(f"loaded {n} india plants", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
