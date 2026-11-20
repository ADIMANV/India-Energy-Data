-- What each conventional station could and couldn't run on a given day, from
-- CEA's daily generation report (dgr2): monitored capacity, capacity under
-- outage, and per unit the outage start, expected return and stated reason.
-- The report already fed cea_state_energy at state×sector×fuel level; its
-- station and unit rows — the only public daily record of which units are
-- down and why — were being thrown away.
CREATE TABLE IF NOT EXISTS station_status (
    as_of        date        NOT NULL,
    zone         text        NOT NULL,
    station      text        NOT NULL,   -- CEA's name, as printed
    station_key  text        NOT NULL,   -- zone|normalised name; joins to web/public/plants.json
    sector       text,
    fuel         text,
    monitored_mw real,
    outage_mw    real,
    actual_mu    real,
    units        jsonb       NOT NULL DEFAULT '[]',
    raw_id       bigint,
    inserted_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (as_of, station_key)
);

CREATE INDEX IF NOT EXISTS station_status_latest ON station_status (as_of DESC);
