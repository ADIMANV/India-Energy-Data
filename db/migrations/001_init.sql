-- 001_init.sql — core tables for India grid timeseries
-- Runs automatically on first container start (mounted at /docker-entrypoint-initdb.d).

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Iron rule #1: archive raw responses before parsing.
CREATE TABLE raw_responses (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source       TEXT        NOT NULL,           -- plugin name, e.g. 'vidyut_pravah'
    endpoint     TEXT        NOT NULL,           -- full URL fetched
    fetched_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    http_status  INT,
    content_type TEXT,
    body         BYTEA       NOT NULL,
    body_sha256  TEXT        NOT NULL,           -- dedupe + schema-drift detection
    meta         JSONB       NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX raw_responses_source_fetched_idx ON raw_responses (source, fetched_at DESC);
CREATE INDEX raw_responses_sha_idx ON raw_responses (source, body_sha256);

-- Parsed timeseries. One row per (zone, metric, fuel, ts, source) observation.
CREATE TABLE datapoints (
    ts             TIMESTAMPTZ      NOT NULL,    -- observation time (IST source, stored UTC)
    zone           TEXT             NOT NULL,    -- 'IN', 'IN-MH', 'IN-WR', ... (ISO 3166-2:IN)
    metric         TEXT             NOT NULL,    -- 'demand_met', 'generation', 'exchange_price', ...
    fuel           TEXT             NOT NULL DEFAULT '',  -- '' when metric has no fuel dimension
    value          DOUBLE PRECISION NOT NULL,
    unit           TEXT             NOT NULL DEFAULT 'MW',-- 'MW', 'MWh', 'INR/kWh', 'MU', 'pct', 'Hz'
    source         TEXT             NOT NULL,    -- plugin name
    parser_version INT              NOT NULL DEFAULT 1,
    raw_id         BIGINT REFERENCES raw_responses (id),
    inserted_at    TIMESTAMPTZ      NOT NULL DEFAULT now(),
    estimated      BOOLEAN          NOT NULL DEFAULT FALSE,
    UNIQUE (zone, metric, fuel, source, ts)
);

SELECT create_hypertable('datapoints', 'ts');
CREATE INDEX datapoints_zone_metric_ts_idx ON datapoints (zone, metric, ts DESC);
