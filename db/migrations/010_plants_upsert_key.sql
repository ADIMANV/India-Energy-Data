-- Stable identity for registry rows so the loader can upsert instead of
-- truncating.
--
-- The loader previously did TRUNCATE ... RESTART IDENTITY, which had two
-- problems once any PSP data existed:
--   1. station_daily.plant_id references india_plants(id), so the truncate
--      simply failed and the registry could never be (re)loaded.
--   2. even where it succeeded, RESTART IDENTITY renumbers ids — silently
--      repointing existing station_daily.plant_id rows at different plants.
-- Upserting on the source's own identifier keeps ids stable across refreshes.
CREATE UNIQUE INDEX IF NOT EXISTS india_plants_source_key
    ON india_plants (source, source_id)
    WHERE source_id IS NOT NULL;
