-- 004_schema_hashes.sql — response-structure tracking for drift alerts
-- Apply to existing DBs:
--   docker compose exec -T db psql -U grid -d india_grid -f /docker-entrypoint-initdb.d/004_schema_hashes.sql

CREATE TABLE IF NOT EXISTS schema_hashes (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source         TEXT NOT NULL,
    kind           TEXT NOT NULL,            -- endpoint family, e.g. 'state-page', 'dynamicData'
    structure_hash TEXT NOT NULL,            -- hash of JSON key-paths / HTML class signature
    first_seen     TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source, kind, structure_hash)
);
