"""Read-only API over the grid timeseries.

    uvicorn gridapi.main:app --port 8000

Endpoints:
    GET /v1/zones                            — all zones + latest demand met
    GET /v1/zone/{id}/live                   — latest value per metric/fuel
    GET /v1/zone/{id}/history?metric=&hours= — timeseries
"""

import csv
import io
import os
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from psycopg_pool import AsyncConnectionPool

DSN = os.environ.get("GRID_DB_DSN", "postgresql://grid:grid@localhost:5433/india_grid")

ZONE_RE = re.compile(r"^IN(-[A-Z]{2})?$")
METRICS = {
    "demand_met", "generation", "exchange_purchase", "exchange_price",
    "peak_shortage", "energy_shortage", "frequency", "net_import",
    "carbon_intensity",
}

pool: AsyncConnectionPool


@asynccontextmanager
async def lifespan(app: FastAPI):
    global pool
    pool = AsyncConnectionPool(DSN, min_size=1, max_size=8, open=False)
    await pool.open()
    yield
    await pool.close()


app = FastAPI(title="India Live Grid API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


def _zone_or_400(zone: str) -> str:
    zone = zone.upper()
    if not ZONE_RE.match(zone):
        raise HTTPException(status_code=400, detail="zone must look like 'IN' or 'IN-MH'")
    return zone


@app.get("/v1/zones")
async def zones():
    """All zones with freshest demand_met and carbon_intensity (any source)."""
    async with pool.connection() as conn:
        demand = await (await conn.execute(
            """
            SELECT DISTINCT ON (zone) zone, value, ts, source
            FROM datapoints
            WHERE metric = 'demand_met' AND ts > now() - interval '24 hours'
            ORDER BY zone, ts DESC, inserted_at DESC
            """
        )).fetchall()
        ci = await (await conn.execute(
            """
            SELECT DISTINCT ON (zone) zone, value, ts, estimated
            FROM datapoints
            WHERE metric = 'carbon_intensity' AND ts > now() - interval '24 hours'
            ORDER BY zone, ts DESC, inserted_at DESC
            """
        )).fetchall()
        bases = await (await conn.execute(
            "SELECT DISTINCT zone, basis FROM current_fuel_shares"
        )).fetchall()
    basis_by_zone = dict(bases)
    ci_by_zone = {z: (v, ts, est) for z, v, ts, est in ci}
    out = []
    for z, v, ts, src in demand:
        entry = {"zone": z, "demand_met_mw": v, "ts": ts.isoformat(), "source": src}
        if z in ci_by_zone:
            cv, cts, cest = ci_by_zone[z]
            entry["carbon_intensity"] = {
                "value": cv, "unit": "gCO2/kWh", "ts": cts.isoformat(), "estimated": cest,
            }
            if cest:
                entry["carbon_intensity"]["estimation_basis"] = basis_by_zone.get(z)
        out.append(entry)
    return {"zones": out}


@app.get("/v1/zone/{zone_id}/live")
async def zone_live(zone_id: str):
    """Latest value per (metric, fuel) for one zone, freshest source wins."""
    zone = _zone_or_400(zone_id)
    async with pool.connection() as conn:
        # non-generation metrics: freshest per metric over 24h
        rows = await (await conn.execute(
            """
            SELECT DISTINCT ON (metric, fuel) metric, fuel, value, unit, ts, source, estimated
            FROM datapoints
            WHERE zone = %s AND metric <> 'generation' AND ts > now() - interval '24 hours'
            ORDER BY metric, fuel, ts DESC, estimated ASC, inserted_at DESC
            """,
            (zone,),
        )).fetchall()
        # live generation mix: one authoritative class — if any real measured
        # fuel row exists in the window use measured, else estimated; never
        # union fuels across the two. own_generation (MERIT aggregate) is kept
        # separate and always passes through.
        has_measured = (await (await conn.execute(
            """
            SELECT EXISTS(
                SELECT 1 FROM datapoints WHERE zone = %s AND metric = 'generation'
                  AND fuel NOT IN ('', 'own_generation') AND estimated = FALSE
                  AND ts > now() - interval '40 minutes')
            """,
            (zone,),
        )).fetchone())[0]
        gen_rows = await (await conn.execute(
            """
            SELECT DISTINCT ON (fuel) metric, fuel, value, unit, ts, source, estimated
            FROM datapoints
            WHERE zone = %s AND metric = 'generation'
              AND ts > now() - interval '40 minutes'
              AND (fuel = 'own_generation' OR estimated = %s)
            ORDER BY fuel, ts DESC, inserted_at DESC
            """,
            (zone, not has_measured),
        )).fetchall()
        rows = list(rows) + list(gen_rows)
        basis_row = await (await conn.execute(
            "SELECT DISTINCT basis FROM current_fuel_shares WHERE zone = %s", (zone,)
        )).fetchone()
        nat_gen = []
        if zone == "IN":
            # national fuel mix = freshest per (state, fuel) summed across states
            nat_gen = await (await conn.execute(
                """
                SELECT fuel, sum(value) AS mw, max(ts) AS ts, bool_or(estimated) AS est
                FROM (
                    SELECT DISTINCT ON (zone, fuel) zone, fuel, value, ts, estimated
                    FROM datapoints
                    WHERE metric = 'generation' AND fuel <> '' AND fuel <> 'own_generation'
                      AND zone <> 'IN' AND ts > now() - interval '30 minutes'
                    ORDER BY zone, fuel, ts DESC, estimated ASC, inserted_at DESC
                ) latest
                GROUP BY fuel ORDER BY mw DESC
                """
            )).fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail=f"no recent data for {zone}")
    basis = basis_row[0] if basis_row else None
    metrics_out = [
        {
            "metric": m, "fuel": f or None, "value": v, "unit": u,
            "ts": ts.isoformat(), "source": src, "estimated": est,
            **({"estimation_basis": basis} if est else {}),
        }
        for m, f, v, u, ts, src, est in rows
    ]
    for f, mw, ts, est in nat_gen:
        metrics_out.append({
            "metric": "generation", "fuel": f, "value": round(mw, 1), "unit": "MW",
            "ts": ts.isoformat(), "source": "state_aggregate", "estimated": est,
        })
    return {"zone": zone, "estimation_basis": basis, "metrics": metrics_out}


@app.get("/v1/status")
async def status():
    """Data-quality: per-source health, cross-check deltas, schema drift, gaps."""
    async with pool.connection() as conn:
        sources = await (await conn.execute(
            """
            SELECT source,
                   max(inserted_at)                                            AS last_success,
                   count(*) FILTER (WHERE inserted_at > now() - interval '24 hours') AS points_24h,
                   count(DISTINCT date_trunc('hour', inserted_at))
                       FILTER (WHERE inserted_at > now() - interval '24 hours')      AS active_hours_24h
            FROM datapoints
            WHERE source <> 'estimate'
            GROUP BY source ORDER BY source
            """
        )).fetchall()
        checks = await (await conn.execute(
            """
            SELECT DISTINCT ON (zone) zone, value_a, value_b, delta_pct, checked_at
            FROM quality_checks ORDER BY zone, checked_at DESC
            """
        )).fetchall()
        drift = await (await conn.execute(
            """
            SELECT source, kind, count(*) AS structures,
                   max(first_seen) AS newest_structure_seen
            FROM schema_hashes GROUP BY source, kind ORDER BY source, kind
            """
        )).fetchall()
        backtests = await (await conn.execute(
            """
            SELECT "check",
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY delta_pct) AS median_delta,
                   round(avg(abs(delta_pct))::numeric, 1) AS mean_abs,
                   count(*) AS zone_days, max(as_of) AS latest
            FROM backtest_daily WHERE as_of > current_date - 7
            GROUP BY "check"
            """
        )).fetchall()
        audit = await (await conn.execute(
            "SELECT audited_at, mwh_match_rate, review_open, review_total "
            "FROM match_audit ORDER BY audited_at DESC LIMIT 1"
        )).fetchone()
        gaps = await (await conn.execute(
            """
            WITH ticks AS (
                SELECT source, inserted_at,
                       inserted_at - lag(inserted_at) OVER (PARTITION BY source ORDER BY inserted_at) AS gap
                FROM (SELECT DISTINCT source, date_trunc('minute', inserted_at) AS inserted_at
                      FROM datapoints
                      WHERE source <> 'estimate' AND inserted_at > now() - interval '24 hours') t)
            SELECT source, max(gap) AS largest_gap_24h FROM ticks GROUP BY source
            """
        )).fetchall()
        # CI accuracy backtest: per-state (independent displayed estimates) +
        # robust headlines (median %, with a small-CI floor so near-zero-carbon
        # hydro states don't blow up the percentage).
        ci_states = await (await conn.execute(
            """
            SELECT zone, max(estimate_basis) AS basis,
                   round(avg(abs_error_g)::numeric, 0) AS mean_abs_g,
                   round(percentile_cont(0.5) WITHIN GROUP (ORDER BY abs(pct_error))::numeric, 1) AS median_abs_pct,
                   round(avg(pct_error)::numeric, 1) AS signed_bias_pct,
                   count(*) AS n_days, round(max(ci_actual)::numeric, 0) AS ci_actual
            FROM ci_backtest
            WHERE estimate_basis <> 'merit_method' AND independent
            GROUP BY zone ORDER BY mean_abs_g
            """
        )).fetchall()

        async def ci_headline(where):
            r = await (await conn.execute(
                f"""SELECT round(percentile_cont(0.5) WITHIN GROUP (ORDER BY abs(pct_error))::numeric,1),
                           round(avg(abs_error_g)::numeric,0), count(*), count(DISTINCT zone)
                    FROM ci_backtest WHERE {where} AND ci_actual >= 100""")).fetchone()
            return {"median_abs_pct": float(r[0]), "mean_abs_g": float(r[1]),
                    "n": r[2], "zones": r[3]} if r and r[2] else None

        ci_merit = await ci_headline("estimate_basis = 'merit_method'")
        ci_overall = await ci_headline("estimate_basis <> 'merit_method' AND independent")
    gap_by_source = {s: g for s, g in gaps}
    return {
        "sources": [
            {
                "source": s,
                "last_success": last.isoformat() if last else None,
                "points_24h": pts,
                # 15-min cadence => up to 24 active hours; uptime = coverage
                "uptime_24h_pct": round(active / 24 * 100, 1),
                "largest_gap_24h": str(gap_by_source.get(s)) if gap_by_source.get(s) else None,
            }
            for s, last, pts, active in sources
        ],
        "cross_checks": [
            {"zone": z, "vidyut_pravah_mw": a, "merit_mw": b,
             "delta_pct": round(d, 2), "checked_at": ts.isoformat()}
            for z, a, b, d, ts in checks
        ],
        "schema_structures": [
            {"source": s, "kind": k, "distinct_structures": int(n),
             "newest_seen": ts.isoformat()}
            for s, k, n, ts in drift
        ],
        "backtests": [
            {"check": c, "median_delta_pct_7d": round(med, 1), "mean_abs_delta_pct_7d": float(ma),
             "zone_days_7d": int(n), "latest": latest.isoformat()}
            for c, med, ma, n, latest in backtests
        ],
        "match_audit": {
            "audited_at": audit[0].isoformat(), "mwh_match_rate": round(audit[1], 3),
            "review_open": audit[2], "review_total": audit[3],
        } if audit else None,
        "ci_accuracy": {
            "overall": ci_overall,
            "merit_method": ci_merit,
            "per_state": [
                {"zone": z, "basis": b, "mean_abs_g": float(ag),
                 "median_abs_pct": float(mp), "signed_bias_pct": float(sb),
                 "n_days": nd, "ci_actual": float(ca)}
                for z, b, ag, mp, sb, nd, ca in ci_states
            ],
        },
    }


@app.get("/v1/zone/{zone_id}/export.csv")
async def export_csv(
    zone_id: str,
    metric: str = Query(default="demand_met"),
    hours: int = Query(default=24, ge=1, le=8760),
):
    """CSV download: ts,zone,metric,fuel,value,unit,source,estimated."""
    zone = _zone_or_400(zone_id)
    if metric not in METRICS:
        raise HTTPException(status_code=400, detail=f"metric must be one of {sorted(METRICS)}")
    async with pool.connection() as conn:
        rows = await (await conn.execute(
            """
            SELECT ts, zone, metric, fuel, value, unit, source, estimated
            FROM datapoints
            WHERE zone = %s AND metric = %s AND ts > now() - make_interval(hours => %s)
            ORDER BY ts
            """,
            (zone, metric, hours),
        )).fetchall()

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["ts", "zone", "metric", "fuel", "value", "unit", "source", "estimated"])
    for ts, z, m, f, v, u, src, est in rows:
        w.writerow([ts.isoformat(), z, m, f, v, u, src, str(est).lower()])
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{zone}_{metric}_{hours}h.csv"'},
    )


@app.get("/v1/zone/{zone_id}/history")
async def zone_history(
    zone_id: str,
    metric: str = Query(default="demand_met", description="single metric or comma-list"),
    hours: int = Query(default=24, ge=1, le=168),
):
    zone = _zone_or_400(zone_id)
    metrics = [m.strip() for m in metric.split(",") if m.strip()]
    bad = [m for m in metrics if m not in METRICS]
    if bad or not metrics:
        raise HTTPException(status_code=400, detail=f"metric must be among {sorted(METRICS)}")
    async with pool.connection() as conn:
        rows = await (await conn.execute(
            """
            SELECT ts, metric, fuel, value, unit, source, estimated
            FROM datapoints
            WHERE zone = %s AND metric = ANY(%s) AND ts > now() - make_interval(hours => %s)
            ORDER BY ts
            """,
            (zone, metrics, hours),
        )).fetchall()
    return {
        "zone": zone,
        "metric": metric,
        "hours": hours,
        "points": [
            {"ts": ts.isoformat(), "metric": m, "fuel": f or None, "value": v, "unit": u,
             "source": src, "estimated": est}
            for ts, m, f, v, u, src, est in rows
        ],
    }
