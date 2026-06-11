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

from . import estimation, fuelmix, sources
from .db import get_dsn
from .quality import cross_check_demand, stale_sources
from .run import run_source


def main() -> int:
    print(f"--- tick {datetime.now(timezone.utc).isoformat(timespec='seconds')}", file=sys.stderr)
    failures: list[str] = []

    with psycopg.connect(get_dsn()) as conn:
        for name in sources.PLUGINS:
            try:
                stats = run_source(sources.load(name), conn)
            except Exception as e:
                failures.append(f"[{name}] run crashed: {e}")
                print(f"[{name}] RUN CRASHED: {e}", file=sys.stderr)
                continue
            for line in stats.errors:
                print(f"  {line}", file=sys.stderr)
            print(stats.report(), file=sys.stderr)
            if not stats.ok:
                failures.append(stats.report())

        try:
            if not fuelmix.shares_fresh(conn):
                print("[fuelmix] shares stale — recomputing from MERIT dispatch", file=sys.stderr)
                fuelmix.compute(conn=conn)
            estimation.run(conn)
        except Exception as e:
            failures.append(f"estimation failed: {e}")
            print(f"ESTIMATION FAILED: {e}", file=sys.stderr)

        offenders = cross_check_demand(conn)
        if offenders:
            failures.append(f"cross-check: {len(offenders)} zones over delta threshold")
        stale = stale_sources(conn)
        if stale:
            failures.append(f"staleness: {[s for s, _ in stale]}")
        conn.commit()

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
