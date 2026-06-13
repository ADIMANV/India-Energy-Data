-- 009_ci_backtest.sql — carbon-intensity accuracy backtest
-- Apply to existing DBs:
--   docker compose exec -T db psql -U grid -d india_grid -f /docker-entrypoint-initdb.d/009_ci_backtest.sql
--
-- One row per (zone, day, estimate_basis). estimate_basis is either the basis
-- that was actually displayed that day (measured / psp_actual_t1 / cea_blend_t1
-- / merit_schedule_t2) or the reconstructed worst-case 'merit_method'.
-- ci_actual = actual fuel-energy split (PSP 2A or CEA dgr2+RE) × the SAME
-- emission_factors.json used live, so the error isolates fuel-SHARE error, not
-- emission-factor disputes. `independent` is false when the actual comes from
-- the same data chain the estimate was derived from (degenerate ~0 check).

CREATE TABLE IF NOT EXISTS ci_backtest (
    zone              TEXT NOT NULL,
    as_of             DATE NOT NULL,
    estimate_basis    TEXT NOT NULL,
    ci_estimated_mean DOUBLE PRECISION NOT NULL,
    ci_actual         DOUBLE PRECISION NOT NULL,
    abs_error_g       DOUBLE PRECISION NOT NULL,
    signed_error_g    DOUBLE PRECISION NOT NULL,  -- estimated − actual
    pct_error         DOUBLE PRECISION NOT NULL,  -- signed, % of actual
    actual_source     TEXT NOT NULL,              -- 'psp' | 'cea'
    independent       BOOLEAN NOT NULL,
    ef_version        INT NOT NULL,
    computed_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (zone, as_of, estimate_basis)
);

CREATE INDEX IF NOT EXISTS ci_backtest_basis_idx ON ci_backtest (estimate_basis, independent);
