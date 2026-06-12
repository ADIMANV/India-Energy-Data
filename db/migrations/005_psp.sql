-- 005_psp.sql — RLDC daily PSP report tables + share provenance
-- Apply to existing DBs:
--   docker compose exec -T db psql -U grid -d india_grid -f /docker-entrypoint-initdb.d/005_psp.sql

-- Section 2A + 2C: state-wise daily energy by fuel (MU), drawal, peak demand
CREATE TABLE IF NOT EXISTS daily_state_energy (
    zone               TEXT NOT NULL,
    as_of              DATE NOT NULL,           -- the day the report describes
    region             TEXT NOT NULL,           -- 'NR', 'WR', ...
    thermal_mu         DOUBLE PRECISION,
    hydro_mu           DOUBLE PRECISION,
    gas_mu             DOUBLE PRECISION,        -- gas/naphtha/diesel column
    solar_mu           DOUBLE PRECISION,
    wind_mu            DOUBLE PRECISION,
    others_mu          DOUBLE PRECISION,        -- biomass/co-gen etc.
    total_gen_mu       DOUBLE PRECISION,        -- report's own total (validation)
    drawal_sch_mu      DOUBLE PRECISION,
    act_drawal_mu      DOUBLE PRECISION,
    ui_mu              DOUBLE PRECISION,
    requirement_mu     DOUBLE PRECISION,
    shortage_mu        DOUBLE PRECISION,
    consumption_mu     DOUBLE PRECISION,
    peak_demand_met_mw DOUBLE PRECISION,        -- section 2C max demand met
    peak_time          TEXT,                    -- 'HH:MM' IST as printed
    source             TEXT NOT NULL,           -- 'psp_nrldc', 'psp_wrldc', ...
    raw_id             BIGINT REFERENCES raw_responses (id),
    parser_version     INT NOT NULL DEFAULT 1,
    inserted_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (zone, as_of)
);

-- Section 3A (+3B central): station-wise daily figures; seeds curtailment work
CREATE TABLE IF NOT EXISTS station_daily (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    zone            TEXT NOT NULL,              -- state zone, or 'IN-NR' for 3B central
    as_of           DATE NOT NULL,
    station_raw     TEXT NOT NULL,              -- name exactly as printed
    fuel            TEXT,                       -- registry/heuristic, NULL if unknown
    inst_capacity_mw DOUBLE PRECISION,
    day_peak_mw     DOUBLE PRECISION,
    day_energy_net_mu DOUBLE PRECISION,
    avg_mw          DOUBLE PRECISION,
    plant_id        BIGINT REFERENCES india_plants (id),  -- registry match if found
    source          TEXT NOT NULL,
    raw_id          BIGINT REFERENCES raw_responses (id),
    inserted_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (zone, as_of, station_raw)
);

-- Reports that failed validation; raw PDF stays in raw_responses
CREATE TABLE IF NOT EXISTS psp_quarantine (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source     TEXT NOT NULL,
    as_of      DATE,
    raw_id     BIGINT REFERENCES raw_responses (id),
    reason     TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Share provenance: PSP T-1 actuals beat MERIT T-2 schedules
ALTER TABLE state_fuel_shares
    ADD COLUMN IF NOT EXISTS basis TEXT NOT NULL DEFAULT 'merit_schedule_t2';
