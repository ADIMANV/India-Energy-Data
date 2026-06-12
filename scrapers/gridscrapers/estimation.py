"""Estimated live fuel mix + carbon intensity (docs/METHODOLOGY.md).

Runs inside the tick after sources. For each state with fuel shares and fresh
demand: writes `generation` datapoints (source='estimate', estimated=true)
and a `carbon_intensity` datapoint. States with measured live mix (Punjab
SLDC) get CI from the measured mix instead, estimated=false. National CI is
the demand-weighted mean of state CIs.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg

from .schema import Datapoint, Metric, Unit
from .db import insert_datapoints
from .zones import NATIONAL

EF_PATH = Path(__file__).parent / "emission_factors.json"
_EF_CONFIG = json.loads(EF_PATH.read_text())
EF: dict[str, float] = {k: v for k, v in _EF_CONFIG["factors"].items() if v is not None}
EF_VERSION: int = _EF_CONFIG["version"]

FRESH_MIN = 30  # demand/mix older than this is not estimated against

# sources that report a real measured fuel mix; estimates never override them
MEASURED_MIX_SOURCES = ("punjab_sldc",)


def _fresh_demand(conn: psycopg.Connection) -> list[tuple]:
    """(zone, value, ts) of freshest demand_met per state within FRESH_MIN."""
    return conn.execute(
        """
        SELECT DISTINCT ON (zone) zone, value, ts
        FROM datapoints
        WHERE metric = 'demand_met' AND zone <> 'IN' AND source <> 'estimate'
          AND ts > now() - make_interval(mins => %s)
        ORDER BY zone, ts DESC, inserted_at DESC
        """,
        (FRESH_MIN,),
    ).fetchall()


def _latest_shares(conn: psycopg.Connection) -> dict[str, dict[str, float]]:
    """Per zone: fuels from current_fuel_shares (PSP actuals beat MERIT)."""
    rows = conn.execute(
        "SELECT zone, fuel, share FROM current_fuel_shares"
    ).fetchall()
    shares: dict[str, dict[str, float]] = {}
    for zone, fuel, share in rows:
        shares.setdefault(zone, {})[fuel] = share
    return shares


def _measured_mix(conn: psycopg.Connection) -> dict[str, tuple[dict[str, float], datetime]]:
    """zone -> ({fuel: mw}, ts) from sources with real per-fuel SCADA."""
    rows = conn.execute(
        """
        SELECT DISTINCT ON (zone, fuel) zone, fuel, value, ts
        FROM datapoints
        WHERE metric = 'generation' AND source = ANY(%s) AND fuel <> ''
          AND ts > now() - make_interval(mins => %s)
        ORDER BY zone, fuel, ts DESC
        """,
        (list(MEASURED_MIX_SOURCES), FRESH_MIN),
    ).fetchall()
    out: dict[str, tuple[dict[str, float], datetime]] = {}
    for zone, fuel, value, ts in rows:
        mix, _ = out.setdefault(zone, ({}, ts))
        mix[fuel] = value
    return out


def _ci_from_shares(shares: dict[str, float]) -> float | None:
    known = {f: s for f, s in shares.items() if f in EF}
    total = sum(known.values())
    if total < 0.5:  # less than half the mix has a factor — refuse to guess
        return None
    return sum(s * EF[f] for f, s in known.items()) / total


def run(conn: psycopg.Connection) -> int:
    """Write estimated mix + CI datapoints. Returns number of points written."""
    demand = _fresh_demand(conn)
    shares = _latest_shares(conn)
    measured = _measured_mix(conn)
    n = 0
    ci_by_zone: dict[str, tuple[float, float]] = {}  # zone -> (ci, demand_mw)

    for zone, demand_mw, ts in demand:
        common = dict(zone=zone, ts=ts, source="estimate", parser_version=EF_VERSION)

        if zone in measured:
            mix, mts = measured[zone]
            total = sum(mix.values())
            if total > 0:
                ci = _ci_from_shares({f: v / total for f, v in mix.items()})
                if ci is not None:
                    n += insert_datapoints(conn, [Datapoint(
                        metric=Metric.CARBON_INTENSITY, value=round(ci, 1),
                        unit=Unit.GCO2_PER_KWH, estimated=False,
                        zone=zone, ts=mts, source="estimate", parser_version=EF_VERSION,
                    )])
                    ci_by_zone[zone] = (ci, demand_mw)
            continue  # measured mix exists: never write estimated generation

        zshares = shares.get(zone)
        if not zshares:
            continue
        points = [
            Datapoint(metric=Metric.GENERATION, fuel=fuel, value=round(share * demand_mw, 1),
                      unit=Unit.MW, estimated=True, **common)
            for fuel, share in zshares.items() if share > 0.0005
        ]
        ci = _ci_from_shares(zshares)
        if ci is not None:
            points.append(Datapoint(metric=Metric.CARBON_INTENSITY, value=round(ci, 1),
                                    unit=Unit.GCO2_PER_KWH, estimated=True, **common))
            ci_by_zone[zone] = (ci, demand_mw)
        n += insert_datapoints(conn, points)

    if ci_by_zone:
        total_mw = sum(d for _, d in ci_by_zone.values())
        nat_ci = sum(ci * d for ci, d in ci_by_zone.values()) / total_mw
        n += insert_datapoints(conn, [Datapoint(
            zone=NATIONAL, ts=datetime.now(timezone.utc).replace(second=0, microsecond=0),
            metric=Metric.CARBON_INTENSITY, value=round(nat_ci, 1),
            unit=Unit.GCO2_PER_KWH, source="estimate", estimated=True,
            parser_version=EF_VERSION,
        )])
    conn.commit()
    print(f"[estimate] {n} datapoints ({len(ci_by_zone)} zones with CI)", file=sys.stderr)
    return n
