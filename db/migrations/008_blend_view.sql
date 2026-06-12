-- 008_blend_view.sql — three-level share-basis preference
-- Apply to existing DBs:
--   docker compose exec -T db psql -U grid -d india_grid -f /docker-entrypoint-initdb.d/008_blend_view.sql
--
-- psp_actual_t1 (+2d bonus) > cea_blend_t1 (+1d) > merit_schedule_t2.
-- Recency bonuses keep a fresh lower-priority basis from shadowing
-- yesterday's better one, while a stalled pipeline eventually loses.

CREATE OR REPLACE VIEW current_fuel_shares AS
WITH ranked AS (
    SELECT zone, as_of, basis,
           row_number() OVER (
               PARTITION BY zone
               ORDER BY as_of + CASE basis
                                    WHEN 'psp_actual_t1' THEN INTERVAL '2 days'
                                    WHEN 'cea_blend_t1' THEN INTERVAL '1 day'
                                    ELSE INTERVAL '0' END DESC,
                        CASE basis
                            WHEN 'psp_actual_t1' THEN 2
                            WHEN 'cea_blend_t1' THEN 1
                            ELSE 0 END DESC
           ) AS rn
    FROM (SELECT DISTINCT zone, as_of, basis FROM state_fuel_shares) d
)
SELECT s.zone, s.as_of, s.basis, s.fuel, s.share, s.match_rate
FROM state_fuel_shares s
JOIN ranked r ON r.zone = s.zone AND r.as_of = s.as_of AND r.basis = s.basis AND r.rn = 1;
