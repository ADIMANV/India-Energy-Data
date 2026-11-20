"""One scheduler tick: run every source, cross-check, staleness check.

Designed for cron (every 15 min, matching Vidyut Pravah's block cadence):
    */15 * * * * cd <repo> && .venv/bin/python -m gridscrapers.tick >> logs/tick.log 2>&1

Fail-loudly contract: exits non-zero on any fetch/parse failure, bounds reject,
empty result, >10% cross-source delta, or stale source. Good datapoints are
still written — failure means "needs attention", not "discard the run".
Optional: set HEALTHCHECK_URL to ping healthchecks.io on success.
"""

import os
import sys
from datetime import datetime, timezone

import httpx
import psycopg

from . import backtest, cea, ci_backtest, estimation, fuelmix, psp, sources
from .db import get_dsn
from .drift import check_drift
from .quality import cross_check_demand, stale_sources
from .run import run_source

# Only one tick at a time. On a small box a slow tick that overlaps the next
# one competes with it for CPU and locks, and the pile-up feeds itself.
TICK_LOCK_KEY = 0x67726964  # "grid"

# Upper bound on any single statement, and on waiting for a lock, so one
# pathological query can never hold the tick (and the next one) hostage.
STEP_TIMEOUT_S = 120
LOCK_TIMEOUT_S = 30


def run_step(conn, name: str, fn, failures: list[str]):
    """Run one post-scrape step in its own transaction.

    A failed SQL statement aborts the whole Postgres transaction, so if steps
    share one, a single broken step — a backtest tripping on one bad day's
    data — makes every later statement fail as well, including the estimate
    that writes each state's fuel mix and carbon intensity. Committing or
    rolling back per step keeps a failure contained to the step that had it.
    Returns the step's result, or None if it failed.
    """
    try:
        out = fn(conn)
        conn.commit()
        return out
    except Exception as e:
        conn.rollback()
        failures.append(f"{name} failed: {e}")
        print(f"{name.upper()} FAILED: {e}", file=sys.stderr)
        return None


def _refresh_mix_and_estimate(conn):
    if not fuelmix.shares_fresh(conn):
        print("[fuelmix] shares stale — recomputing from MERIT dispatch", file=sys.stderr)
        fuelmix.compute(conn=conn)
    return estimation.run(conn)


def main() -> int:
    print(f"--- tick {datetime.now(timezone.utc).isoformat(timespec='seconds')}", file=sys.stderr)
    failures: list[str] = []

    with psycopg.connect(get_dsn()) as conn:
        if not conn.execute("SELECT pg_try_advisory_lock(%s)", (TICK_LOCK_KEY,)).fetchone()[0]:
            print("previous tick still running — skipping this one", file=sys.stderr)
            return 1
        # session-wide, so they hold even across the commits some steps make
        conn.execute("SELECT set_config('statement_timeout', %s, false)", (f"{STEP_TIMEOUT_S}s",))
        conn.execute("SELECT set_config('lock_timeout', %s, false)", (f"{LOCK_TIMEOUT_S}s",))
        conn.commit()

        for name in sources.PLUGINS:
            try:
                stats, raws = run_source(sources.load(name), conn)
            except Exception as e:
                conn.rollback()
                failures.append(f"[{name}] run crashed: {e}")
                print(f"[{name}] RUN CRASHED: {e}", file=sys.stderr)
                continue
            for line in stats.errors:
                print(f"  {line}", file=sys.stderr)
            print(stats.report(), file=sys.stderr)
            if not stats.ok:
                failures.append(stats.report())
            failures.extend(check_drift(conn, raws))
            conn.commit()

        # Inputs to the estimate first (T-1 reports; each a no-op once ingested),
        # then the estimate itself — the fuel mix and carbon intensity the site
        # exists to show — and only then the diagnostics, which are the heaviest
        # steps and must never stand between the scrapers and the estimate.
        run_step(conn, "psp ingest", psp.ensure_current, failures)
        run_step(conn, "cea ingest", cea.ensure_current, failures)
        run_step(conn, "estimation", _refresh_mix_and_estimate, failures)

        run_step(conn, "demand backtest", backtest.run_daily, failures)
        run_step(conn, "ci backtest", ci_backtest.run, failures)
        failures.extend(run_step(conn, "drift alerts", backtest.drift_alerts, failures) or [])
        failures.extend(run_step(conn, "match audit", backtest.weekly_match_audit, failures) or [])

        offenders = run_step(conn, "cross-check", cross_check_demand, failures)
        if offenders:
            failures.append(f"cross-check: {len(offenders)} zones over delta threshold")
        stale = run_step(conn, "staleness check", stale_sources, failures)
        if stale:
            failures.append(f"staleness: {[s for s, _ in stale]}")

    if failures:
        print(f"TICK FAILED ({len(failures)} issues)", file=sys.stderr)
        return 1

    if url := os.environ.get("HEALTHCHECK_URL"):
        try:
            httpx.get(url, timeout=10)
        except httpx.HTTPError as e:
            print(f"healthcheck ping failed: {e}", file=sys.stderr)

    print("TICK OK", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
