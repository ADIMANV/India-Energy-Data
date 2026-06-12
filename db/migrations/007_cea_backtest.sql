-- 007_cea_backtest.sql — CEA daily generation + backtest + match audit
-- Apply to existing DBs:
--   docker compose exec -T db psql -U grid -d india_grid -f /docker-entrypoint-initdb.d/007_cea_backtest.sql

-- NPP/CEA dgr2: state × sector × fuel daily energy (conventional stations)
CREATE TABLE IF NOT EXISTS cea_state_energy (
    zone        TEXT NOT NULL,
    as_of       DATE NOT NULL,
    sector      TEXT NOT NULL,        -- STATE / PVT / CENTRAL
    fuel        TEXT NOT NULL,        -- coal, gas, oil, hydro, nuclear, other
    capacity_mw DOUBLE PRECISION,
    program_mu  DOUBLE PRECISION,
    actual_mu   DOUBLE PRECISION,
    source      TEXT NOT NULL DEFAULT 'cea_dgr',
    raw_id      BIGINT REFERENCES raw_responses (id),
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (zone, as_of, sector, fuel)
);

-- Cross-source daily backtests (see gridscrapers/backtest.py for checks)
CREATE TABLE IF NOT EXISTS backtest_daily (
    zone       TEXT NOT NULL,
    as_of      DATE NOT NULL,
    "check"    TEXT NOT NULL,         -- 'demand_integral_vs_psp', 'cea_vs_psp_owngen'
    value_a    DOUBLE PRECISION NOT NULL,
    value_b    DOUBLE PRECISION NOT NULL,
    delta_pct  DOUBLE PRECISION NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (zone, as_of, "check")
);

-- Weekly MERIT match-rate snapshots (registry / station-name drift detector)
CREATE TABLE IF NOT EXISTS match_audit (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    audited_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    mwh_match_rate  DOUBLE PRECISION NOT NULL,   -- MWh-weighted, merit basis
    review_open     INT NOT NULL,
    review_total    INT NOT NULL
);
