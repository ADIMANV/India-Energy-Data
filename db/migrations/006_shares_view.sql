-- 006_shares_view.sql — one canonical "which shares apply now" rule
-- Apply to existing DBs:
--   docker compose exec -T db psql -U grid -d india_grid -f /docker-entrypoint-initdb.d/006_shares_view.sql
--
-- Preference: PSP T-1 actuals beat MERIT T-2 schedules. A psp basis gets a
-- 2-day recency bonus so a fresh MERIT run never shadows yesterday's actuals,
-- but if PSP ingestion stalls for days the freshest data wins again.

CREATE OR REPLACE VIEW current_fuel_shares AS
WITH ranked AS (
    SELECT zone, as_of, basis,
           row_number() OVER (
               PARTITION BY zone
               ORDER BY as_of + CASE WHEN basis = 'psp_actual_t1'
                                     THEN INTERVAL '2 days' ELSE INTERVAL '0' END DESC,
                        (basis = 'psp_actual_t1') DESC
           ) AS rn
    FROM (SELECT DISTINCT zone, as_of, basis FROM state_fuel_shares) d
)
SELECT s.zone, s.as_of, s.basis, s.fuel, s.share, s.match_rate
FROM state_fuel_shares s
JOIN ranked r ON r.zone = s.zone AND r.as_of = s.as_of AND r.basis = s.basis AND r.rn = 1;
