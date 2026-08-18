"""Postgres/Timescale writer: raw archive first, then parsed datapoints."""

import hashlib
import json
import os

import psycopg

from .schema import Datapoint, RawResponse

DEFAULT_DSN = "postgresql://grid:grid@localhost:5433/india_grid"


def get_dsn() -> str:
    return os.environ.get("GRID_DB_DSN", DEFAULT_DSN)


def archive_raw(conn: psycopg.Connection, raw: RawResponse) -> int:
    """Insert a raw response, return its id. Always call before parsing."""
    sha = hashlib.sha256(raw.body).hexdigest()
    row = conn.execute(
        """
        INSERT INTO raw_responses (source, endpoint, fetched_at, http_status, content_type, body, body_sha256, meta)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            raw.source,
            raw.endpoint,
            raw.fetched_at,
            raw.http_status,
            raw.content_type,
            raw.body,
            sha,
            json.dumps(raw.meta),
        ),
    ).fetchone()
    assert row is not None
    return row[0]


def insert_datapoints(
    conn: psycopg.Connection, points: list[Datapoint], raw_id: int | None = None
) -> int:
    """Upsert datapoints; re-scrapes of the same time block overwrite in place."""
    n = 0
    with conn.cursor() as cur:
        for p in points:
            cur.execute(
                """
                INSERT INTO datapoints (ts, zone, metric, fuel, value, unit, source, parser_version, raw_id, estimated)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (zone, metric, fuel, source, ts)
                DO UPDATE SET value = EXCLUDED.value, raw_id = EXCLUDED.raw_id,
                              parser_version = EXCLUDED.parser_version, inserted_at = now()
                """,
                (
                    p.ts,
                    p.zone,
                    p.metric.value,
                    p.fuel,
                    p.value,
                    p.unit.value,
                    p.source,
                    p.parser_version,
                    raw_id,
                    p.estimated,
                ),
            )
            n += 1
    return n
