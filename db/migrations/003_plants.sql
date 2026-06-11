-- 003_plants.sql — plant registry + fuel-share estimation tables
-- Apply to existing DBs:
--   docker compose exec -T db psql -U grid -d india_grid -f /docker-entrypoint-initdb.d/003_plants.sql

-- Power plant registry (loaded from powerplantmatching / GPPD; see
-- `python -m gridscrapers.plants load` and docs/METHODOLOGY.md)
CREATE TABLE IF NOT EXISTS india_plants (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name        TEXT NOT NULL,
    fuel        TEXT NOT NULL,            -- coal, gas, oil, hydro, nuclear, solar, wind, biomass, other
    capacity_mw DOUBLE PRECISION,
    lat         DOUBLE PRECISION,
    lon         DOUBLE PRECISION,
    state_zone  TEXT,                     -- IN-XX via point-in-polygon, NULL if unknown
    source      TEXT NOT NULL,            -- 'powerplantmatching' | 'gppd'
    source_id   TEXT,
    loaded_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS india_plants_fuel_idx ON india_plants (fuel);
CREATE INDEX IF NOT EXISTS india_plants_state_idx ON india_plants (state_zone);

-- MERIT dispatch rows that didn't match any registry plant — review queue
CREATE TABLE IF NOT EXISTS plant_match_review (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    zone           TEXT NOT NULL,
    merit_station  TEXT NOT NULL,
    merit_type     TEXT,
    schedule_mwh   DOUBLE PRECISION,
    best_candidate TEXT,
    best_score     DOUBLE PRECISION,
    fallback_fuel  TEXT,                  -- fuel assumed from MERIT type
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved       BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE (zone, merit_station)
);

-- Per-state fuel shares derived from MERIT plant-wise dispatch (daily, T-2)
CREATE TABLE IF NOT EXISTS state_fuel_shares (
    zone        TEXT NOT NULL,
    as_of       DATE NOT NULL,            -- dispatch date the shares describe
    fuel        TEXT NOT NULL,
    share       DOUBLE PRECISION NOT NULL CHECK (share >= 0 AND share <= 1),
    match_rate  DOUBLE PRECISION,         -- fraction of MWh matched to registry
    computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (zone, as_of, fuel)
);
