"""Scraper runner: fetch → archive raw → parse → insert datapoints.

Usage:
    python -m gridscrapers.run vidyut_pravah [--dry-run]
    GRID_DB_DSN=postgresql://... python -m gridscrapers.run merit
"""

import argparse
import sys

import psycopg

from . import sources
from .db import archive_raw, get_dsn, insert_datapoints


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("source", help=f"one of {sources.PLUGINS}")
    ap.add_argument("--dry-run", action="store_true", help="fetch+parse, print, no DB writes")
    args = ap.parse_args()

    plugin = sources.load(args.source)
    raws = plugin.fetch()
    fetch_failures = [r for r in raws if "error" in r.meta or (r.http_status or 0) != 200]
    print(
        f"[{plugin.SOURCE}] fetched {len(raws)} responses ({len(fetch_failures)} failed)",
        file=sys.stderr,
    )
    for r in fetch_failures:
        print(f"  FETCH FAIL {r.endpoint}: status={r.http_status} {r.meta.get('error', '')}", file=sys.stderr)

    total = 0
    failures = 0
    if args.dry_run:
        for raw in raws:
            try:
                points = plugin.parse(raw)
            except Exception as e:
                failures += 1
                print(f"  PARSE FAIL {raw.endpoint}: {e}", file=sys.stderr)
                continue
            total += len(points)
            for p in points:
                print(p.model_dump_json())
    else:
        with psycopg.connect(get_dsn()) as conn:
            for raw in raws:
                raw_id = archive_raw(conn, raw)  # archive even if parsing fails
                try:
                    points = plugin.parse(raw)
                except Exception as e:
                    failures += 1
                    print(f"  PARSE FAIL {raw.endpoint} (raw_id={raw_id}): {e}", file=sys.stderr)
                    continue
                total += insert_datapoints(conn, points, raw_id=raw_id)
            conn.commit()

    print(f"[{plugin.SOURCE}] {total} datapoints, {failures} parse failures", file=sys.stderr)
    return 1 if failures and not total else 0


if __name__ == "__main__":
    sys.exit(main())
