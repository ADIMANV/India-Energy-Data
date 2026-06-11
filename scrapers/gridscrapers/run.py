"""Scraper runner: fetch → archive raw → parse → bounds-check → insert.

Usage:
    python -m gridscrapers.run vidyut_pravah [--dry-run]
    GRID_DB_DSN=postgresql://... python -m gridscrapers.run merit
"""

import argparse
import sys
from dataclasses import dataclass, field
from types import ModuleType

import psycopg

from . import sources
from .db import archive_raw, get_dsn, insert_datapoints
from .quality import split_by_bounds


@dataclass
class RunStats:
    source: str
    fetched: int = 0
    fetch_failures: int = 0
    parse_failures: int = 0
    bounds_rejects: int = 0
    inserted: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return (
            self.inserted > 0
            and not self.parse_failures
            and not self.bounds_rejects
            and not self.fetch_failures
        )

    def report(self) -> str:
        return (
            f"[{self.source}] fetched={self.fetched} (fail={self.fetch_failures}) "
            f"inserted={self.inserted} parse_fail={self.parse_failures} "
            f"bounds_reject={self.bounds_rejects}"
        )


def run_source(plugin: ModuleType, conn: psycopg.Connection) -> tuple[RunStats, list]:
    """Run one plugin end-to-end. Raw is archived even when parsing fails.

    Returns (stats, raws) — raws feed the schema-drift check in the tick.
    """
    stats = RunStats(source=plugin.SOURCE)
    raws = plugin.fetch()
    stats.fetched = len(raws)
    for raw in raws:
        if "error" in raw.meta or (raw.http_status or 0) != 200:
            stats.fetch_failures += 1
            stats.errors.append(
                f"FETCH FAIL {raw.endpoint}: status={raw.http_status} {raw.meta.get('error', '')}"
            )
        raw_id = archive_raw(conn, raw)
        try:
            points = plugin.parse(raw)
        except Exception as e:
            stats.parse_failures += 1
            stats.errors.append(f"PARSE FAIL {raw.endpoint} (raw_id={raw_id}): {e}")
            continue
        ok_points, bad_points = split_by_bounds(points)
        for p in bad_points:
            stats.bounds_rejects += 1
            stats.errors.append(
                f"BOUNDS REJECT {p.zone} {p.metric}={p.value} {p.unit} (raw_id={raw_id})"
            )
        stats.inserted += insert_datapoints(conn, ok_points, raw_id=raw_id)
    conn.commit()
    return stats, raws


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("source", help=f"one of {sources.PLUGINS}")
    ap.add_argument("--dry-run", action="store_true", help="fetch+parse, print, no DB writes")
    args = ap.parse_args()
    plugin = sources.load(args.source)

    if args.dry_run:
        raws = plugin.fetch()
        n = 0
        for raw in raws:
            try:
                points = plugin.parse(raw)
            except Exception as e:
                print(f"PARSE FAIL {raw.endpoint}: {e}", file=sys.stderr)
                continue
            n += len(points)
            for p in points:
                print(p.model_dump_json())
        print(f"[{plugin.SOURCE}] fetched {len(raws)}, {n} datapoints", file=sys.stderr)
        return 0

    with psycopg.connect(get_dsn()) as conn:
        stats, _ = run_source(plugin, conn)
    for line in stats.errors:
        print(f"  {line}", file=sys.stderr)
    print(stats.report(), file=sys.stderr)
    return 0 if stats.ok else 1


if __name__ == "__main__":
    sys.exit(main())
