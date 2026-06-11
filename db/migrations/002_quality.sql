-- 002_quality.sql — cross-source data-quality checks
-- Note: docker-entrypoint-initdb.d only runs on first init; apply to existing
-- DBs with: docker compose exec -T db psql -U grid -d india_grid -f /docker-entrypoint-initdb.d/002_quality.sql

CREATE TABLE IF NOT EXISTS quality_checks (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    checked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    zone       TEXT NOT NULL,
    metric     TEXT NOT NULL,
    source_a   TEXT NOT NULL,
    value_a    DOUBLE PRECISION NOT NULL,
    ts_a       TIMESTAMPTZ NOT NULL,
    source_b   TEXT NOT NULL,
    value_b    DOUBLE PRECISION NOT NULL,
    ts_b       TIMESTAMPTZ NOT NULL,
    delta_pct  DOUBLE PRECISION NOT NULL   -- (a-b)/b * 100
);

CREATE INDEX IF NOT EXISTS quality_checks_zone_idx ON quality_checks (zone, checked_at DESC);
