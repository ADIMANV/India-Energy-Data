"""Data-quality gates.

1. Sanity bounds per metric — out-of-range values are rejected before insert
   ("fail loudly, never write garbage").
2. Cross-source check — compare fresh demand_met between vidyut_pravah and
   merit per zone; record delta in quality_checks, warn above threshold.
3. Staleness — warn when a source has written nothing recently.
"""

import sys

import psycopg

from .schema import Datapoint, Metric

# value bounds by metric (units as stored: MW / INR/kWh / MU)
BOUNDS: dict[Metric, tuple[float, float]] = {
    Metric.DEMAND_MET: (0, 400_000),       # national peak ~250 GW; headroom
    Metric.GENERATION: (0, 400_000),
    Metric.EXCHANGE_PURCHASE: (-50_000, 50_000),
    Metric.EXCHANGE_PRICE: (0, 25),        # IEX price cap ~ Rs 20/kWh
    Metric.PEAK_SHORTAGE: (0, 100_000),
    Metric.ENERGY_SHORTAGE: (0, 10_000),
    Metric.NET_IMPORT: (-100_000, 100_000),
    Metric.FREQUENCY: (45, 55),
    Metric.CARBON_INTENSITY: (0, 1200),
}

CROSS_CHECK_WARN_PCT = 10.0
CROSS_CHECK_WARN_MIN_MW = 100.0  # tiny states: 20 MW of noise is not an alert
STALENESS_LIMIT_MIN = 20


def in_bounds(p: Datapoint) -> bool:
    lo, hi = BOUNDS.get(p.metric, (float("-inf"), float("inf")))
    return lo <= p.value <= hi


def split_by_bounds(points: list[Datapoint]) -> tuple[list[Datapoint], list[Datapoint]]:
    ok = [p for p in points if in_bounds(p)]
    bad = [p for p in points if not in_bounds(p)]
    return ok, bad


def cross_check_demand(conn: psycopg.Connection, window_min: int = 30) -> list[tuple]:
    """Compare freshest demand_met from vidyut_pravah vs merit per zone.

    Inserts one quality_checks row per overlapping zone; returns rows whose
    |delta_pct| exceeds CROSS_CHECK_WARN_PCT.
    """
    rows = conn.execute(
        """
        WITH latest AS (
            SELECT DISTINCT ON (zone, source) zone, source, value, ts
            FROM datapoints
            WHERE metric = 'demand_met'
              AND zone <> 'IN'
              AND ts > now() - make_interval(mins => %s)
            ORDER BY zone, source, ts DESC
        )
        SELECT a.zone, a.value, a.ts, b.value, b.ts
        FROM latest a
        JOIN latest b USING (zone)
        WHERE a.source = 'vidyut_pravah' AND b.source = 'merit' AND b.value <> 0
        """,
        (window_min,),
    ).fetchall()

    offenders = []
    with conn.cursor() as cur:
        for zone, va, ta, vb, tb in rows:
            delta_pct = (va - vb) / vb * 100
            cur.execute(
                """
                INSERT INTO quality_checks (zone, metric, source_a, value_a, ts_a, source_b, value_b, ts_b, delta_pct)
                VALUES (%s, 'demand_met', 'vidyut_pravah', %s, %s, 'merit', %s, %s, %s)
                """,
                (zone, va, ta, vb, tb, delta_pct),
            )
            if abs(delta_pct) > CROSS_CHECK_WARN_PCT and abs(va - vb) > CROSS_CHECK_WARN_MIN_MW:
                offenders.append((zone, va, vb, delta_pct))
                print(
                    f"QUALITY WARN {zone}: vidyut_pravah={va:.0f} MW vs merit={vb:.0f} MW "
                    f"(delta {delta_pct:+.1f}%)",
                    file=sys.stderr,
                )
    return offenders


def stale_sources(conn: psycopg.Connection, limit_min: int = STALENESS_LIMIT_MIN) -> list[tuple]:
    """Sources whose newest insert is older than limit_min minutes."""
    rows = conn.execute(
        """
        SELECT source, max(inserted_at) AS last_seen
        FROM datapoints
        GROUP BY source
        HAVING max(inserted_at) < now() - make_interval(mins => %s)
        """,
        (limit_min,),
    ).fetchall()
    for source, last_seen in rows:
        print(f"STALENESS WARN {source}: no new datapoints since {last_seen}", file=sys.stderr)
    return rows
