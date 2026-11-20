"""India's extra-high-voltage transmission backbone, as a static file for the map.

    python -m gridscrapers.gridlines export [--out web/public/gridlines.json]

Pulls every OpenStreetMap power=line at 400 kV and above inside India from the
Overpass API, simplifies it for country-scale drawing, and writes GeoJSON with
one property per line: its highest voltage in kV. Lines at 220 kV and below
are left out on purpose — there are tens of thousands, and at the zooms this
map is read at they'd only add noise.

This is mapped geometry, not flow: OpenStreetMap records where lines run, not
what they carry. Data © OpenStreetMap contributors, ODbL — the map credits it.
"""

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
QUERY = """
[out:json][timeout:240];
area["ISO3166-1"="IN"][admin_level=2]->.in;
way["power"="line"]["voltage"~"(^|;)(400000|500000|765000|800000)(;|$)"](area.in);
out geom;
"""
TOLERANCE = 0.004  # degrees, ~400 m: invisible at the zooms the map opens at
USER_AGENT = "india-electricity-data (https://github.com/ADIMANV/India-Energy-Data)"


def fetch(attempts: int = 12, wait_s: int = 60) -> dict:
    """Overpass mirrors shed load with 502/504s; cycle through them patiently."""
    last = None
    for i in range(attempts):
        url = ENDPOINTS[i % len(ENDPOINTS)]
        try:
            r = httpx.post(url, data={"data": QUERY}, timeout=300,
                           headers={"User-Agent": USER_AGENT})
            if r.status_code == 200:
                return r.json()
            last = f"{url}: HTTP {r.status_code}"
        except httpx.HTTPError as e:
            last = f"{url}: {e}"
        print(f"[gridlines] attempt {i + 1} failed ({last}); retrying in {wait_s}s", file=sys.stderr)
        time.sleep(wait_s)
    raise RuntimeError(f"Overpass unavailable after {attempts} attempts ({last})")


def _simplify(pts: list, tol: float) -> list:
    """Douglas–Peucker, iterative."""
    if len(pts) <= 2:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        (ax, ay), (bx, by) = pts[i], pts[j]
        dx, dy = bx - ax, by - ay
        len2 = dx * dx + dy * dy or 1e-18
        best, best_d = -1, tol
        for k in range(i + 1, j):
            px, py = pts[k]
            t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / len2))
            d = ((px - ax - t * dx) ** 2 + (py - ay - t * dy) ** 2) ** 0.5
            if d > best_d:
                best, best_d = k, d
        if best >= 0:
            keep[best] = True
            stack += [(i, best), (best, j)]
    return [p for p, k in zip(pts, keep) if k]


def to_geojson(osm: dict) -> dict:
    """One MultiLineString per voltage class.

    OSM splits a single line into many ways (11k+ at 400 kV and up); as
    separate features their JSON wrapping outweighs the coordinates. Merged by
    class the file is a fraction of the size and draws identically.
    """
    by_kv: dict[int, list] = {}
    for el in osm.get("elements", []):
        geom = el.get("geometry") or []
        if len(geom) < 2:
            continue
        volts = [int(v) for v in el.get("tags", {}).get("voltage", "").split(";") if v.isdigit()]
        if not volts:
            continue
        pts = _simplify([(g["lon"], g["lat"]) for g in geom], TOLERANCE)
        by_kv.setdefault(max(volts) // 1000, []).append([[round(x, 4), round(y, 4)] for x, y in pts])
    return {
        "type": "FeatureCollection",
        "attribution": "© OpenStreetMap contributors (ODbL)",
        "features": [
            {"type": "Feature", "properties": {"kv": kv, "ways": len(lines)},
             "geometry": {"type": "MultiLineString", "coordinates": lines}}
            for kv, lines in sorted(by_kv.items())
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", choices=["export"])
    ap.add_argument("--out", default=str(Path(__file__).parents[2] / "web/public/gridlines.json"))
    args = ap.parse_args()
    doc = to_geojson(fetch())
    Path(args.out).write_text(json.dumps(doc, separators=(",", ":")))
    ways = sum(f["properties"]["ways"] for f in doc["features"])
    pts = sum(len(line) for f in doc["features"] for line in f["geometry"]["coordinates"])
    print(f"[gridlines] {ways} ways in {len(doc['features'])} voltage classes, "
          f"{pts:,} vertices → {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
