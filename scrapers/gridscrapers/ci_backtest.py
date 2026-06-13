"""Carbon-intensity accuracy backtest.

Quantifies how close our estimated CI is to CI recomputed from *actual* fuel
energy, per state-day. The actual CI uses the SAME emission_factors.json the
live pipeline uses, so any error is in the fuel SHARES we estimate, not in the
emission factors (those are a separate, documented choice).

Two products, both into `ci_backtest`:

1. Displayed-estimate rows — `ci_estimated_mean` is the daily mean of our
   archived live CI; `estimate_basis` is the basis that won that day
   (measured / psp_actual_t1 / cea_blend_t1 / merit_schedule_t2). The actual
   is taken from a DIFFERENT data chain where possible (`independent=true`);
   a same-chain check (psp estimate vs PSP actual) is degenerate ~0 and is
   marked `independent=false` so it can be excluded from headlines.

2. Worst-case method rows — `estimate_basis='merit_method'`: reconstruct what
   the pure MERIT-schedule-T-2 estimate would have produced and compare to
   actual. Always independent (MERIT vs PSP/CEA). This bounds trust for the
   merit-only and grey (unestimated) states — the headline credibility metric.

Validation: a measured state (Punjab) must show a small but NON-zero error
(measured SCADA mix vs PSP-report energy are different instruments). ~0 would
mean the check went circular.
"""

import sys
from datetime import date

import psycopg

from .estimation import EF, EF_VERSION, _ci_from_shares

# basis → data-chain family, for the independence test
BASIS_FAMILY = {
    "measured": "sldc",
    "psp_actual_t1": "psp",
    "cea_blend_t1": "cea",
    "merit_schedule_t2": "merit",
    "merit_method": "merit",
}

# PSP 2A columns → our EF fuel vocabulary
PSP_FUELS = {
    "thermal_mu": "coal", "hydro_mu": "hydro", "gas_mu": "gas",
    "solar_mu": "solar", "wind_mu": "wind", "others_mu": "res_nonsolar",
}


def _psp_actual_ci(conn, zone, day) -> float | None:
    row = conn.execute(
        "SELECT thermal_mu, hydro_mu, gas_mu, solar_mu, wind_mu, others_mu "
        "FROM daily_state_energy WHERE zone=%s AND as_of=%s",
        (zone, day),
    ).fetchone()
    if not row:
        return None
    energy = {fuel: (v or 0.0) for (col, fuel), v in zip(PSP_FUELS.items(), row)}
    return _ci_from_shares(energy)


def _cea_actual_ci(conn, zone, day) -> float | None:
    rows = conn.execute(
        "SELECT fuel, sum(actual_mu) FROM cea_state_energy "
        "WHERE zone=%s AND as_of=%s AND actual_mu > 0 GROUP BY fuel",
        (zone, day),
    ).fetchall()
    if not rows:
        return None
    return _ci_from_shares({f: float(v) for f, v in rows if f in EF})


ACTUALS = {"psp": _psp_actual_ci, "cea": _cea_actual_ci}


def _effective_basis(conn, zone, day) -> str | None:
    """The basis that was displayed for this zone-day."""
    measured = conn.execute(
        "SELECT bool_or(NOT estimated) FROM datapoints "
        "WHERE zone=%s AND metric='carbon_intensity' AND ts::date=%s",
        (zone, day),
    ).fetchone()[0]
    if measured:
        return "measured"
    bases = {r[0] for r in conn.execute(
        "SELECT DISTINCT basis FROM state_fuel_shares WHERE zone=%s AND as_of=%s",
        (zone, day),
    ).fetchall()}
    for b in ("psp_actual_t1", "cea_blend_t1", "merit_schedule_t2"):
        if b in bases:
            return b
    return None


def _pick_actual(conn, zone, day, family: str):
    """Prefer an actual from a DIFFERENT chain than the estimate (independent).
    Returns (source, ci, independent) or None."""
    avail = {src: ci for src, fn in ACTUALS.items() if (ci := fn(conn, zone, day)) is not None}
    if not avail:
        return None
    independent = [s for s in avail if s != family]
    for s in ("psp", "cea"):  # psp first — richer split incl. RE
        if s in independent:
            return s, avail[s], True
    src = next(iter(avail))  # only same-chain actual available → degenerate
    return src, avail[src], False


def _store(conn, zone, day, basis, ci_est, ci_act, source, independent) -> None:
    abs_err = abs(ci_est - ci_act)
    signed = ci_est - ci_act
    pct = signed / ci_act * 100 if ci_act else 0.0
    conn.execute(
        """
        INSERT INTO ci_backtest (zone, as_of, estimate_basis, ci_estimated_mean,
            ci_actual, abs_error_g, signed_error_g, pct_error, actual_source,
            independent, ef_version)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (zone, as_of, estimate_basis) DO UPDATE SET
            ci_estimated_mean=EXCLUDED.ci_estimated_mean, ci_actual=EXCLUDED.ci_actual,
            abs_error_g=EXCLUDED.abs_error_g, signed_error_g=EXCLUDED.signed_error_g,
            pct_error=EXCLUDED.pct_error, actual_source=EXCLUDED.actual_source,
            independent=EXCLUDED.independent, ef_version=EXCLUDED.ef_version,
            computed_at=now()
        """,
        (zone, day, basis, round(ci_est, 1), round(ci_act, 1), round(abs_err, 1),
         round(signed, 1), round(pct, 2), source, independent, EF_VERSION),
    )


def run(conn: psycopg.Connection) -> int:
    """Backfill/refresh ci_backtest across all archived history."""
    n = 0

    # 1. Displayed-estimate rows: one per (zone, day) with archived live CI.
    #    ci_estimated_mean is demand-weighted (Σ CI·demand / Σ demand) so it
    #    matches the energy-weighted actual and isolates fuel-share error from
    #    the time-of-day weighting of a plain mean.
    est_days = conn.execute(
        """
        WITH ci AS (
            SELECT zone, ts, value AS ci FROM datapoints
            WHERE metric='carbon_intensity' AND zone<>'IN'),
        dem AS (
            SELECT zone, ts, value AS mw FROM datapoints
            WHERE metric='demand_met' AND source<>'estimate')
        SELECT ci.zone, ci.ts::date AS day,
               sum(ci.ci * coalesce(dem.mw, 1)) / sum(coalesce(dem.mw, 1))
        FROM ci LEFT JOIN dem USING (zone, ts)
        GROUP BY ci.zone, ci.ts::date
        """
    ).fetchall()
    for zone, day, ci_mean in est_days:
        basis = _effective_basis(conn, zone, day)
        if basis is None:
            continue
        picked = _pick_actual(conn, zone, day, BASIS_FAMILY[basis])
        if picked is None:
            continue
        source, ci_act, independent = picked
        _store(conn, zone, day, basis, float(ci_mean), ci_act, source, independent)
        n += 1

    # 2. Worst-case MERIT-method rows: reconstruct merit-schedule CI vs actual
    #    for every (zone, day) where merit shares and an actual both exist.
    merit = conn.execute(
        "SELECT zone, as_of, fuel, share FROM state_fuel_shares "
        "WHERE basis='merit_schedule_t2'"
    ).fetchall()
    by_zd: dict[tuple, dict] = {}
    for zone, as_of, fuel, share in merit:
        by_zd.setdefault((zone, as_of), {})[fuel] = share
    for (zone, day), shares in by_zd.items():
        ci_est = _ci_from_shares(shares)
        if ci_est is None:
            continue
        picked = _pick_actual(conn, zone, day, "merit")
        if picked is None:
            continue
        source, ci_act, _ = picked
        _store(conn, zone, day, "merit_method", ci_est, ci_act, source, True)
        n += 1

    conn.commit()
    print(f"[ci_backtest] {n} state-day rows", file=sys.stderr)
    return n


# % error is unstable for near-zero-carbon (hydro/RE) states — a 30 g miss on
# a 25 g actual is 120% but trivial in absolute terms. Headlines use the MEDIAN
# (robust to those) over cells whose actual CI clears this floor; the per-state
# table still shows every cell with its absolute g error.
PCT_STABLE_FLOOR_G = 100.0


def summary(conn: psycopg.Connection) -> dict:
    """Per-state accuracy (independent displayed estimates) + merit-method headline."""
    per_state = conn.execute(
        """
        SELECT zone,
               max(estimate_basis) AS basis,
               round(avg(abs_error_g)::numeric, 0) AS mean_abs_g,
               round(percentile_cont(0.5) WITHIN GROUP (ORDER BY abs(pct_error))::numeric, 1) AS median_abs_pct,
               round(avg(pct_error)::numeric, 1) AS signed_bias_pct,
               count(*) AS n_days,
               max(ci_actual) AS ci_actual
        FROM ci_backtest
        WHERE estimate_basis <> 'merit_method' AND independent
        GROUP BY zone ORDER BY mean_abs_g
        """
    ).fetchall()

    def headline(where: str) -> dict | None:
        row = conn.execute(
            f"""
            SELECT round(percentile_cont(0.5) WITHIN GROUP (ORDER BY abs(pct_error))::numeric, 1),
                   round(avg(abs_error_g)::numeric, 0),
                   count(*), count(DISTINCT zone)
            FROM ci_backtest WHERE {where} AND ci_actual >= %s
            """,
            (PCT_STABLE_FLOOR_G,),
        ).fetchone()
        return {"median_abs_pct": row[0], "mean_abs_g": row[1], "n": row[2], "zones": row[3]} \
            if row and row[2] else None

    return {
        "per_state": [
            {"zone": z, "basis": b, "mean_abs_g": ag, "median_abs_pct": mp,
             "signed_bias_pct": sb, "n_days": nd, "ci_actual": round(ca)}
            for z, b, ag, mp, sb, nd, ca in per_state
        ],
        "merit_method": headline("estimate_basis = 'merit_method'"),
        "overall": headline("estimate_basis <> 'merit_method' AND independent"),
    }
