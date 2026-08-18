"""Per-state fuel shares from MERIT plant-wise dispatch (daily, ~T-2).

    python -m gridscrapers.fuelmix compute [--date "09 Jun 2026"]

Pipeline per state: POST GetPowerStationData → archive raw → for each plant
row, decide fuel:
  - MERIT TypeOfGeneration is authoritative for Hydro / Nuclear / Gas;
    aggregated rows TOTAL SOLAR → solar, TOTAL NON SOLAR → res_nonsolar
    (wind + biomass + small hydro blend, see docs/METHODOLOGY.md)
  - "Thermal" is ambiguous (coal/lignite/gas/oil) → fuzzy-match the station
    name against india_plants; fall back to coal (the Indian thermal default)
    and queue the row in plant_match_review.

Shares are scheduled-MWh fractions over the state's dispatch table, written
to state_fuel_shares with the MWh-weighted registry match rate.
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path

import psycopg

from .db import archive_raw, get_dsn
from .http import IST, make_client, request_raw
from .schema import RawResponse
from .sources.merit import BASE, STATE_CODES

SOURCE = "merit_dispatch"
MATCH_THRESHOLD = 0.72
OVERRIDES_PATH = Path(__file__).parents[2] / "data/plant_overrides.json"


def load_overrides() -> dict[str, dict[str, str]]:
    """zone -> {merit_station: fuel}. Curated, wins over fuzzy matching."""
    if not OVERRIDES_PATH.exists():
        return {}
    data = json.loads(OVERRIDES_PATH.read_text())
    return {
        zone: {station: spec["fuel"] for station, spec in stations.items()}
        for zone, stations in data.get("overrides", {}).items()
    }

TYPE_FUEL = {
    "hydro": "hydro",
    "nuclear": "nuclear",
    "gas": "gas",
    "lignite": "coal",
}
THERMAL_FUELS = {"coal", "gas", "oil"}

_STOPWORDS = re.compile(
    r"\b(stps|tps|sstps|stage|st|unit|units|ps|hep|hps|gps|ccpp|ctps|tpp|plant|"
    r"power|project|station|super|thermal|hydro|gen|co|ltd|i+v?|v|\d+)\b"
)
_NONALPHA = re.compile(r"[^a-z ]")


def _norm(name: str) -> str:
    s = _NONALPHA.sub(" ", name.lower())
    s = _STOPWORDS.sub(" ", s)
    return " ".join(s.split())


def _score(a: str, b: str) -> float:
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return 0.0
    base = SequenceMatcher(None, na, nb).ratio()
    # containment bonus: MERIT names are abbreviations of registry names
    if na in nb or nb in na:
        base = max(base, 0.8)
    ta, tb = set(na.split()), set(nb.split())
    if ta and ta <= tb:
        base = max(base, 0.85)
    return base


def fetch_dispatch(client, code: str, zone: str, date_str: str) -> RawResponse:
    return request_raw(
        client, SOURCE, "POST", f"{BASE}/StateWiseDetails/GetPowerStationData",
        json={"StateCode": code, "date": date_str},
        meta={"zone": zone, "state_code": code, "dispatch_date": date_str},
    )


def _mwh(s: str | None) -> float:
    try:
        return float((s or "0").replace(",", ""))
    except ValueError:
        return 0.0


def compute_state(
    conn: psycopg.Connection,
    raw: RawResponse,
    registry: list[tuple],
    overrides: dict[str, dict[str, str]] | None = None,
) -> dict | None:
    """Returns {fuel: share} or None if no usable rows. Writes review rows."""
    zone = raw.meta["zone"]
    zone_overrides = (overrides or {}).get(zone, {})
    if not raw.body or (raw.http_status or 0) != 200:
        return None
    try:
        rows = json.loads(raw.body)
    except json.JSONDecodeError:
        return None
    if not isinstance(rows, list) or not rows:
        return None

    by_fuel: dict[str, float] = {}
    matched_mwh = total_mwh = 0.0
    for r in rows:
        name = (r.get("PowerStationName") or "").strip()
        mwh = _mwh(r.get("Schedule"))
        mtype = (r.get("TypeOfGeneration") or "").strip().lower()
        if mwh <= 0:
            continue
        total_mwh += mwh

        if name in zone_overrides:
            fuel = zone_overrides[name]
            by_fuel[fuel] = by_fuel.get(fuel, 0) + mwh
            matched_mwh += mwh
            continue

        up = name.upper()
        if "SOLAR" in up and up.startswith("TOTAL"):
            fuel = "solar" if "NON" not in up else "res_nonsolar"
            by_fuel[fuel] = by_fuel.get(fuel, 0) + mwh
            matched_mwh += mwh  # aggregate rows are authoritative, count as matched
            continue
        if mtype in TYPE_FUEL:
            by_fuel[TYPE_FUEL[mtype]] = by_fuel.get(TYPE_FUEL[mtype], 0) + mwh
            matched_mwh += mwh
            continue
        if mtype == "renewable":
            by_fuel["res_nonsolar"] = by_fuel.get("res_nonsolar", 0) + mwh
            matched_mwh += mwh
            continue

        # thermal (or unknown type): try the registry
        best, best_score = None, 0.0
        for pname, pfuel in registry:
            if mtype == "thermal" and pfuel not in THERMAL_FUELS:
                continue
            s = _score(name, pname)
            if s > best_score:
                best, best_score = (pname, pfuel), s
        if best and best_score >= MATCH_THRESHOLD:
            by_fuel[best[1]] = by_fuel.get(best[1], 0) + mwh
            matched_mwh += mwh
        else:
            fallback = "coal" if mtype == "thermal" else "other"
            by_fuel[fallback] = by_fuel.get(fallback, 0) + mwh
            conn.execute(
                """INSERT INTO plant_match_review
                   (zone, merit_station, merit_type, schedule_mwh, best_candidate, best_score, fallback_fuel)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (zone, merit_station) DO UPDATE
                   SET schedule_mwh = EXCLUDED.schedule_mwh, best_candidate = EXCLUDED.best_candidate,
                       best_score = EXCLUDED.best_score, created_at = now()""",
                (zone, name, mtype, mwh, best[0] if best else None, best_score, fallback),
            )

    if total_mwh <= 0:
        return None
    return {
        "shares": {f: v / total_mwh for f, v in by_fuel.items()},
        "match_rate": matched_mwh / total_mwh,
    }


def compute(date_str: str | None = None, conn: psycopg.Connection | None = None) -> int:
    """Fetch dispatch for every MERIT state and persist fuel shares. Returns #states."""
    if date_str is None:
        date_str = (datetime.now(IST) - timedelta(days=2)).strftime("%d %b %Y")
    as_of = datetime.strptime(date_str, "%d %b %Y").date()

    own_conn = conn is None
    if own_conn:
        conn = psycopg.connect(get_dsn())
    registry = conn.execute("SELECT name, fuel FROM india_plants").fetchall()
    overrides = load_overrides()
    for zone, stations in overrides.items():
        conn.execute(
            "UPDATE plant_match_review SET resolved = TRUE WHERE zone = %s AND merit_station = ANY(%s)",
            (zone, list(stations)),
        )

    n = 0
    with make_client(verify=False) as client:
        for code, zone in STATE_CODES.items():
            raw = fetch_dispatch(client, code, zone, date_str)
            archive_raw(conn, raw)
            result = compute_state(conn, raw, registry, overrides)
            if result is None:
                print(f"  no dispatch data for {zone} ({date_str})", file=sys.stderr)
                time.sleep(0.5)
                continue
            # full replace: a fuel absent from the new mix must not linger
            conn.execute(
                "DELETE FROM state_fuel_shares WHERE zone = %s AND as_of = %s", (zone, as_of)
            )
            for fuel, share in result["shares"].items():
                conn.execute(
                    """INSERT INTO state_fuel_shares (zone, as_of, fuel, share, match_rate)
                       VALUES (%s,%s,%s,%s,%s)
                       ON CONFLICT (zone, as_of, fuel) DO UPDATE
                       SET share = EXCLUDED.share, match_rate = EXCLUDED.match_rate, computed_at = now()""",
                    (zone, as_of, fuel, share, result["match_rate"]),
                )
            print(f"  {zone}: {len(result['shares'])} fuels, match_rate={result['match_rate']:.0%}", file=sys.stderr)
            n += 1
            time.sleep(0.5)
    conn.commit()
    if own_conn:
        conn.close()
    return n


def shares_fresh(conn: psycopg.Connection, max_age_days: int = 5) -> bool:
    # merit basis only: psp rows refresh daily and must not mask a stale merit set
    row = conn.execute(
        "SELECT max(as_of) FROM state_fuel_shares WHERE basis = 'merit_schedule_t2'"
    ).fetchone()
    return row[0] is not None and (datetime.now(IST).date() - row[0]).days <= max_age_days


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", choices=["compute"])
    ap.add_argument("--date", help='dispatch date like "09 Jun 2026" (default: today-2)')
    args = ap.parse_args()
    n = compute(args.date)
    print(f"computed shares for {n} states", file=sys.stderr)
    return 0 if n else 1


if __name__ == "__main__":
    sys.exit(main())
