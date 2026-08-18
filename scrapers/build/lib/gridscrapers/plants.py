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
GEOJSON_PATH = Path(__file__).parents[2] / "web/public/india_states.geojson"

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


def load_state_geoms(path: Path = GEOJSON_PATH) -> list[tuple[str, dict]]:
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
        ))

    with psycopg.connect(get_dsn()) as conn:
        conn.execute("TRUNCATE india_plants RESTART IDENTITY")
        with conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO india_plants (name, fuel, capacity_mw, lat, lon, state_zone, source, source_id)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
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
