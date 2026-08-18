"""Cross-source daily backtests + weekly match-rate audit.

Checks (backtest_daily table, surfaced on /status):
  demand_integral_vs_psp — our 15-min demand_met samples integrated to daily
      MU vs the RLDC PSP report's consumption_mu. Validates the live
      pipeline against T-1 actuals. Needs ≥40 samples in the day.
  cea_vs_psp_owngen — CEA dgr2 STATE+PVT conventional MU vs PSP 2A own
      control-area generation (thermal+gas+hydro). Scope differs slightly
      (CEA groups by plant location and omits RE), so the alert is on
      *systematic* drift, not single days.

Alert rule ("systematic drift"): both checks carry known, stable scope
biases (CEA groups plants by location, PSP by control area — Uttarakhand's
private hydro exports make CEA ~+70% there permanently). So the alert fires
when the RELATIONSHIP moves: per check, |median delta of last 7 days −
median delta of the prior baseline window| > 5pp. Absolute deltas stay
visible on /status; a standing bias never pages, a parser/source change does.

Weekly audit (match_audit table): snapshot of the MERIT MWh-weighted match
rate + review-queue depth; alerts when the rate drops >5pp from the previous
audit (GPPD registry or MERIT station-name drift).
"""

import sys
from datetime import datetime, timedelta

import psycopg

DRIFT_PCT = 5.0
AUDIT_INTERVAL_DAYS = 7
AUDIT_DROP_PP = 5.0


def run_daily(conn: psycopg.Connection) -> int:
    """Compute both checks for any days that have the needed inputs."""
    n = 0
    # our demand integral vs PSP consumption
    n += conn.execute(
        """
        INSERT INTO backtest_daily (zone, as_of, "check", value_a, value_b, delta_pct)
        SELECT d.zone, p.as_of, 'demand_integral_vs_psp',
               d.avg_mw * 24 / 1000.0       AS ours_mu,
               p.consumption_mu             AS psp_mu,
               (d.avg_mw * 24 / 1000.0 - p.consumption_mu) / p.consumption_mu * 100
        FROM daily_state_energy p
        JOIN (
            SELECT zone, ts::date AS day, avg(value) AS avg_mw, count(*) AS samples
            FROM datapoints
            WHERE metric = 'demand_met' AND source IN ('vidyut_pravah', 'merit')
            GROUP BY zone, ts::date
        ) d ON d.zone = p.zone AND d.day = p.as_of
        WHERE p.consumption_mu > 1 AND d.samples >= 80  -- ≥20h of 15-min coverage
        ON CONFLICT (zone, as_of, "check") DO UPDATE
            SET value_a = EXCLUDED.value_a, value_b = EXCLUDED.value_b,
                delta_pct = EXCLUDED.delta_pct, created_at = now()
        """
    ).rowcount
    # CEA state+pvt conventional vs PSP own generation
    n += conn.execute(
        """
        INSERT INTO backtest_daily (zone, as_of, "check", value_a, value_b, delta_pct)
        SELECT c.zone, c.as_of, 'cea_vs_psp_owngen', c.cea_mu, p.own_mu,
               (c.cea_mu - p.own_mu) / p.own_mu * 100
        FROM (
            SELECT zone, as_of, sum(actual_mu) AS cea_mu
            FROM cea_state_energy
            WHERE sector IN ('STATE', 'PVT') AND fuel IN ('coal', 'gas', 'oil', 'hydro')
            GROUP BY zone, as_of
        ) c
        JOIN (
            SELECT zone, as_of,
                   coalesce(thermal_mu,0) + coalesce(gas_mu,0) + coalesce(hydro_mu,0) AS own_mu
            FROM daily_state_energy
        ) p USING (zone, as_of)
        WHERE p.own_mu > 5
        ON CONFLICT (zone, as_of, "check") DO UPDATE
            SET value_a = EXCLUDED.value_a, value_b = EXCLUDED.value_b,
                delta_pct = EXCLUDED.delta_pct, created_at = now()
        """
    ).rowcount
    return n


def drift_alerts(conn: psycopg.Connection) -> list[str]:
    """Alert when the cross-source relationship shifts, not on standing bias."""
    rows = conn.execute(
        """
        WITH recent AS (
            SELECT "check", percentile_cont(0.5) WITHIN GROUP (ORDER BY delta_pct) AS med,
                   count(*) AS n
            FROM backtest_daily WHERE as_of > current_date - 7
            GROUP BY "check"
        ), baseline AS (
            SELECT "check", percentile_cont(0.5) WITHIN GROUP (ORDER BY delta_pct) AS med,
                   count(*) AS n
            FROM backtest_daily
            WHERE as_of <= current_date - 7 AND as_of > current_date - 37
            GROUP BY "check"
        )
        SELECT r."check", r.med, b.med, r.n, b.n
        FROM recent r JOIN baseline b USING ("check")
        WHERE b.n >= 10 AND abs(r.med - b.med) > %s
        """,
        (DRIFT_PCT,),
    ).fetchall()
    alerts = []
    for check, recent_med, base_med, rn, bn in rows:
        msg = (f"BACKTEST DRIFT {check}: 7d median delta {recent_med:+.1f}% vs "
               f"baseline {base_med:+.1f}% (n={rn}/{bn}) — relationship shifted")
        alerts.append(msg)
        print(msg, file=sys.stderr)
    return alerts


def weekly_match_audit(conn: psycopg.Connection) -> list[str]:
    """Snapshot match rate weekly; alert on a drop (registry/name drift)."""
    last = conn.execute("SELECT max(audited_at) FROM match_audit").fetchone()[0]
    if last and (datetime.now(last.tzinfo) - last).days < AUDIT_INTERVAL_DAYS:
        return []
    rate_row = conn.execute(
        """
        SELECT sum(share * match_rate) / nullif(sum(share), 0)
        FROM state_fuel_shares
        WHERE basis = 'merit_schedule_t2'
          AND as_of = (SELECT max(as_of) FROM state_fuel_shares WHERE basis = 'merit_schedule_t2')
        """
    ).fetchone()
    rate = rate_row[0]
    if rate is None:
        return []
    open_n, total_n = conn.execute(
        "SELECT count(*) FILTER (WHERE NOT resolved), count(*) FROM plant_match_review"
    ).fetchone()
    prev = conn.execute(
        "SELECT mwh_match_rate FROM match_audit ORDER BY audited_at DESC LIMIT 1"
    ).fetchone()
    conn.execute(
        "INSERT INTO match_audit (mwh_match_rate, review_open, review_total) VALUES (%s,%s,%s)",
        (rate, open_n, total_n),
    )
    print(f"[audit] match_rate={rate:.1%} review_open={open_n}/{total_n}", file=sys.stderr)
    if prev and (prev[0] - rate) * 100 > AUDIT_DROP_PP:
        msg = (f"MATCH-RATE DROP: {prev[0]:.1%} -> {rate:.1%} "
               f"(registry or MERIT station-name drift; review queue {open_n} open)")
        print(msg, file=sys.stderr)
        return [msg]
    return []
