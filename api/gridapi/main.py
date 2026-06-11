"""Read-only API over the grid timeseries.

    uvicorn gridapi.main:app --port 8000

Endpoints:
    GET /v1/zones                            — all zones + latest demand met
    GET /v1/zone/{id}/live                   — latest value per metric/fuel
    GET /v1/zone/{id}/history?metric=&hours= — timeseries
"""

import os
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from psycopg_pool import AsyncConnectionPool

DSN = os.environ.get("GRID_DB_DSN", "postgresql://grid:grid@localhost:5433/india_grid")

ZONE_RE = re.compile(r"^IN(-[A-Z]{2})?$")
METRICS = {
    "demand_met", "generation", "exchange_purchase", "exchange_price",
    "peak_shortage", "energy_shortage", "frequency", "net_import",
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
    """All zones with their freshest demand_met (any source)."""
    async with pool.connection() as conn:
        rows = await (await conn.execute(
            """
            SELECT DISTINCT ON (zone) zone, value, ts, source
            FROM datapoints
            WHERE metric = 'demand_met' AND ts > now() - interval '24 hours'
            ORDER BY zone, ts DESC, inserted_at DESC
            """
        )).fetchall()
    return {
        "zones": [
            {"zone": z, "demand_met_mw": v, "ts": ts.isoformat(), "source": src}
            for z, v, ts, src in rows
        ]
    }


@app.get("/v1/zone/{zone_id}/live")
async def zone_live(zone_id: str):
    """Latest value per (metric, fuel) for one zone, freshest source wins."""
    zone = _zone_or_400(zone_id)
    async with pool.connection() as conn:
        rows = await (await conn.execute(
            """
            SELECT DISTINCT ON (metric, fuel) metric, fuel, value, unit, ts, source
            FROM datapoints
            WHERE zone = %s AND ts > now() - interval '24 hours'
            ORDER BY metric, fuel, ts DESC, inserted_at DESC
            """,
            (zone,),
        )).fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail=f"no recent data for {zone}")
    return {
        "zone": zone,
        "metrics": [
            {
                "metric": m, "fuel": f or None, "value": v, "unit": u,
                "ts": ts.isoformat(), "source": src,
            }
            for m, f, v, u, ts, src in rows
        ],
    }


@app.get("/v1/zone/{zone_id}/history")
async def zone_history(
    zone_id: str,
    metric: str = Query(default="demand_met"),
    hours: int = Query(default=24, ge=1, le=168),
):
    zone = _zone_or_400(zone_id)
    if metric not in METRICS:
        raise HTTPException(status_code=400, detail=f"metric must be one of {sorted(METRICS)}")
    async with pool.connection() as conn:
        rows = await (await conn.execute(
            """
            SELECT ts, fuel, value, unit, source
            FROM datapoints
            WHERE zone = %s AND metric = %s AND ts > now() - make_interval(hours => %s)
            ORDER BY ts
            """,
            (zone, metric, hours),
        )).fetchall()
    return {
        "zone": zone,
        "metric": metric,
        "hours": hours,
        "points": [
            {"ts": ts.isoformat(), "fuel": f or None, "value": v, "unit": u, "source": src}
            for ts, f, v, u, src in rows
        ],
    }
