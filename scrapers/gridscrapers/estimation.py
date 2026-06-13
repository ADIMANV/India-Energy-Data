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
from zoneinfo import ZoneInfo

import psycopg

from . import solar
from .schema import Datapoint, Metric, Unit
from .db import insert_datapoints
from .zones import NATIONAL

IST = ZoneInfo("Asia/Kolkata")
RE_FLAT_FUELS = ("wind", "res_nonsolar", "biomass")
RE_CAP_FRAC = 0.95  # RE never exceeds 95% of instantaneous demand

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


def _avg_demand_24h(conn: psycopg.Connection) -> dict[str, float]:
    rows = conn.execute(
        """
        SELECT zone, avg(value) FROM datapoints
        WHERE metric = 'demand_met' AND source <> 'estimate'
          AND ts > now() - interval '24 hours'
        GROUP BY zone
        """
    ).fetchall()
    return dict(rows)


def shaped_mix(zone: str, zshares: dict[str, float], demand_mw: float,
               d_avg_mw: float, ts_utc: datetime) -> dict[str, float]:
    """Intra-day mix in MW: solar follows the clear-sky curve, wind and other
    RE run flat at their daily-average MW, conventional fuels absorb the
    residual in proportion to their daily energy split. Sums to demand_mw."""
    w = solar.weight(zone, ts_utc.astimezone(IST))
    solar_mw = zshares.get("solar", 0.0) * d_avg_mw * w
    re_flat = {f: zshares.get(f, 0.0) * d_avg_mw for f in RE_FLAT_FUELS}
    re_total = solar_mw + sum(re_flat.values())
    cap = RE_CAP_FRAC * demand_mw
    if re_total > cap > 0:
        k = cap / re_total
        solar_mw *= k
        re_flat = {f: v * k for f, v in re_flat.items()}
        re_total = cap
    conv_shares = {f: s for f, s in zshares.items()
                   if f not in RE_FLAT_FUELS and f != "solar" and s > 0}
    conv_sum = sum(conv_shares.values())
    conv_mw = max(demand_mw - re_total, 0.0)
    mix = {f: conv_mw * s / conv_sum for f, s in conv_shares.items()} if conv_sum else {}
    if solar_mw > 0:
        mix["solar"] = solar_mw
    mix.update({f: v for f, v in re_flat.items() if v > 0})
    return mix


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
    d_avg = _avg_demand_24h(conn)
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
        mix = shaped_mix(zone, zshares, demand_mw, d_avg.get(zone, demand_mw), ts)
        points = [
            Datapoint(metric=Metric.GENERATION, fuel=fuel, value=round(mw, 1),
                      unit=Unit.MW, estimated=True, **common)
            for fuel, mw in mix.items() if mw > 0.1
        ]
        ci = _ci_from_shares(mix)
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


def recompute_window(conn: psycopg.Connection, hours: int = 24,
                     zones: list[str] | None = None) -> int:
    """Re-derive estimated generation + CI for stored demand samples in the
    window (e.g. after a shaping/methodology change). Overwrites in place."""
    shares = _latest_shares(conn)
    d_avg = _avg_demand_24h(conn)
    rows = conn.execute(
        """
        SELECT DISTINCT ON (zone, ts) zone, value, ts
        FROM datapoints
        WHERE metric = 'demand_met' AND zone <> 'IN' AND source <> 'estimate'
          AND ts > now() - make_interval(hours => %s)
        ORDER BY zone, ts, inserted_at DESC
        """,
        (hours,),
    ).fetchall()
    n = 0
    for zone, demand_mw, ts in rows:
        if zones and zone not in zones:
            continue
        zshares = shares.get(zone)
        if not zshares or zone in MEASURED_MIX_SOURCES:
            continue
        mix = shaped_mix(zone, zshares, demand_mw, d_avg.get(zone, demand_mw), ts)
        common = dict(zone=zone, ts=ts, source="estimate", parser_version=EF_VERSION)
        points = [
            Datapoint(metric=Metric.GENERATION, fuel=fuel, value=round(mw, 1),
                      unit=Unit.MW, estimated=True, **common)
            for fuel, mw in mix.items() if mw > 0.1
        ]
        ci = _ci_from_shares(mix)
        if ci is not None:
            points.append(Datapoint(metric=Metric.CARBON_INTENSITY, value=round(ci, 1),
                                    unit=Unit.GCO2_PER_KWH, estimated=True, **common))
        n += insert_datapoints(conn, points)
    conn.commit()
    return n
