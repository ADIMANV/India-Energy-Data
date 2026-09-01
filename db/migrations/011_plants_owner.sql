-- GPPD ships an `owner` and `commissioning_year` for every plant and the loader
-- was discarding both, even though the file is already downloaded.
--
-- Coverage is poor for India — as of the 2026-08 snapshot only ~21% of Indian
-- plants carry an owner, and those cover ~4% of capacity, with NTPC (the
-- country's largest generator) absent entirely. That is not enough to publish a
-- public/private split from; CEA's sector-wise installed capacity is the source
-- for that. These columns are stored so the gap is measurable rather than
-- invisible, and so the field is ready if a better registry appears.
ALTER TABLE india_plants ADD COLUMN IF NOT EXISTS owner text;
ALTER TABLE india_plants ADD COLUMN IF NOT EXISTS commissioning_year int;

CREATE INDEX IF NOT EXISTS india_plants_owner_idx ON india_plants (owner)
    WHERE owner IS NOT NULL;
