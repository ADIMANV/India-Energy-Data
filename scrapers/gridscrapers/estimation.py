"""Estimated live fuel mix + carbon intensity (docs/METHODOLOGY.md).

Runs inside the tick after sources. For each state with fuel shares and fresh
demand: writes `generation` datapoints (source='estimate', estimated=true)
and a `carbon_intensity` datapoint. States with measured live mix (Punjab
SLDC) get CI from the measured mix instead, estimated=false. National CI is
the generation-weighted mean of state CIs (= total emissions / total
generation), i.e. Σ(CI_z·gen_z)/Σ(gen_z).
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
from .sources import MEASURED_MIX_SOURCES, OWN_GENERATION_SOURCES
from .zones import NATIONAL

IST = ZoneInfo("Asia/Kolkata")
RE_FLAT_FUELS = ("wind", "res_nonsolar", "biomass")
RE_CAP_FRAC = 0.95  # RE never exceeds 95% of instantaneous demand

# A full-mix measured source (one that reports a state's whole generation, not
# just its own fleet) should produce a total within this band of demand. Outside
# it the parser has almost certainly dropped rows or doubled a unit — distrust
# the mix, drop it, and fall back to the estimate so it can't skew national CI.
RECONCILE_BAND = (0.5, 2.0)  # measured gen / demand

EF_PATH = Path(__file__).parent / "emission_factors.json"
_EF_CONFIG = json.loads(EF_PATH.read_text())
EF: dict[str, float] = {k: v for k, v in _EF_CONFIG["factors"].items() if v is not None}
EF_VERSION: int = _EF_CONFIG["version"]

FRESH_MIN = 30  # demand/mix older than this is not estimated against


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


def _measured_mix(conn: psycopg.Connection) -> dict[str, tuple[dict[str, float], datetime, str]]:
    """zone -> ({fuel: mw}, ts, source) from sources with real per-fuel SCADA."""
    rows = conn.execute(
        """
        SELECT DISTINCT ON (zone, fuel) zone, fuel, value, ts, source
        FROM datapoints
        WHERE metric = 'generation' AND source = ANY(%s) AND fuel <> ''
          AND ts > now() - make_interval(mins => %s)
        ORDER BY zone, fuel, ts DESC
        """,
        (list(MEASURED_MIX_SOURCES), FRESH_MIN),
    ).fetchall()
    out: dict[str, tuple[dict[str, float], datetime, str]] = {}
    for zone, fuel, value, ts, source in rows:
        if zone not in out:
            out[zone] = ({}, ts, source)
        out[zone][0][fuel] = value
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


def _mix_trusted(src: str, total_mw: float, demand_mw: float) -> bool:
    """Reconcile guard. A measured mix is trusted when it has generation and —
    for full-mix sources — its total lands within RECONCILE_BAND of demand.
    Own-generation sources (Delhi) report a partial fleet by design and are
    exempt. With no demand to check against we don't reject. A full-mix total
    far from demand means the parser dropped rows / doubled a unit, so the mix
    is distrusted and the caller falls back to the estimate."""
    if total_mw <= 0:
        return False
    if src in OWN_GENERATION_SOURCES or demand_mw <= 0:
        return True
    lo, hi = RECONCILE_BAND
    return lo * demand_mw <= total_mw <= hi * demand_mw


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
    ci_by_zone: dict[str, tuple[float, float]] = {}  # zone -> (ci, gen_mw)

    for zone, demand_mw, ts in demand:
        common = dict(zone=zone, ts=ts, source="estimate", parser_version=EF_VERSION)

        if zone in measured:
            mix, mts, src = measured[zone]
            total = sum(mix.values())
            if _mix_trusted(src, total, demand_mw):
                # purge stale estimated generation so the donut shows only the
                # measured mix (a freshly-measured zone may still have estimate
                # rows inside the fresh window from before its plugin landed)
                conn.execute(
                    """DELETE FROM datapoints WHERE zone = %s AND metric = 'generation'
                       AND source = 'estimate' AND ts > now() - make_interval(mins => %s)""",
                    (zone, FRESH_MIN),
                )
                ci = _ci_from_shares({f: v / total for f, v in mix.items()})
                if ci is not None:
                    n += insert_datapoints(conn, [Datapoint(
                        metric=Metric.CARBON_INTENSITY, value=round(ci, 1),
                        unit=Unit.GCO2_PER_KWH, estimated=False,
                        zone=zone, ts=mts, source="estimate", parser_version=EF_VERSION,
                    )])
                    # weight by measured generation, not demand (they differ for
                    # import/export-heavy states); CI is a per-kWh-generated figure
                    ci_by_zone[zone] = (ci, total)
                continue  # trusted measured mix: never write estimated generation
            if total > 0:
                # a measured mix arrived but failed the reconcile guard: drop it
                # so /live + the donut fall back to the estimate too; the plugin
                # re-inserts next tick and wins again if it recovers (self-healing)
                conn.execute(
                    """DELETE FROM datapoints WHERE zone = %s AND metric = 'generation'
                       AND source = ANY(%s) AND estimated = FALSE
                       AND ts > now() - make_interval(mins => %s)""",
                    (zone, list(MEASURED_MIX_SOURCES), FRESH_MIN),
                )
                lo, hi = RECONCILE_BAND
                print(f"[estimate] {zone}: {src} measured mix failed reconcile "
                      f"(gen {total:.0f} MW vs demand {demand_mw:.0f} MW, "
                      f"band {lo:.0%}-{hi:.0%}) — dropped, using estimate", file=sys.stderr)
            # fall through to the estimated path below

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
            # shaped_mix sums to demand_mw, so gen == demand for estimated zones
            ci_by_zone[zone] = (ci, sum(mix.values()))
        n += insert_datapoints(conn, points)

    if ci_by_zone:
        # national = total emissions / total generation = Σ(CI_z·gen_z)/Σ(gen_z)
        gen_mw = sum(g for _, g in ci_by_zone.values())
        nat_ci = sum(ci * g for ci, g in ci_by_zone.values()) / gen_mw
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
