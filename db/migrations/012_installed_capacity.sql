-- CEA installed capacity by state, sector and fuel.
--
-- Answers the question the plant registry cannot: how much of a state's
-- capacity is state-owned, centrally owned or private. GPPD's owner field
-- covers ~4% of Indian capacity, so this is the only usable public source for
-- a public/private split (see docs/DATA_GAPS.md §5).
--
-- Capacity, NOT generation — solar and wind run at far lower capacity factors
-- than coal, so a 54% private capacity share is not a 54% private generation
-- share. Anything derived from this table must say which it is.
--
-- Monthly cadence: CEA publishes one workbook per month, so as_of is the
-- report's own "as on" date rather than an ingest timestamp.
CREATE TABLE IF NOT EXISTS cea_installed_capacity (
    as_of        date              NOT NULL,
    zone         text              NOT NULL,
    sector       text              NOT NULL,  -- state | private | central
    fuel         text              NOT NULL,  -- coal|lignite|gas|diesel|nuclear|hydro|res
    capacity_mw  double precision,
    raw_id       bigint REFERENCES raw_responses (id),
    loaded_at    timestamptz       NOT NULL DEFAULT now(),
    PRIMARY KEY (as_of, zone, sector, fuel)
);

CREATE INDEX IF NOT EXISTS cea_installed_capacity_zone_idx
    ON cea_installed_capacity (zone, as_of DESC);
