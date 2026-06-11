"""Schema-drift detection from response structure.

A structure hash ignores values and captures shape:
  - JSON: sha256 of the sorted set of key paths ($.a.b, $.items[].name)
  - HTML: sha256 of the sorted set of css classes + ids that our parsers key on

Each tick, hashes for fetched raws are upserted into schema_hashes per
(source, kind). A kind whose newest hash was never seen before, while an
older hash exists, is drift → loud warning (tick fails). Value-only changes
never trigger; markup/key changes always do.
"""

import hashlib
import json
import re
import sys

import psycopg

from .schema import RawResponse

_CLASS_RE = re.compile(rb'(?:class|id)="([^"]+)"')


def _json_paths(node, prefix: str, out: set) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            _json_paths(v, f"{prefix}.{k}", out)
    elif isinstance(node, list):
        for v in node[:5]:
            _json_paths(v, f"{prefix}[]", out)
    else:
        out.add(prefix)


def structure_hash(raw: RawResponse) -> str | None:
    if not raw.body or (raw.http_status or 0) != 200:
        return None
    body = raw.body.strip()
    if body[:1] in (b"{", b"["):
        try:
            paths: set = set()
            _json_paths(json.loads(body), "$", paths)
            sig = "\n".join(sorted(paths))
        except ValueError:
            return None
    else:
        tokens = sorted({t.decode("utf-8", "replace") for m in _CLASS_RE.finditer(body)
                         for t in m.group(1).split()})
        sig = "\n".join(tokens)
    return hashlib.sha256(sig.encode()).hexdigest()


def kind_of(raw: RawResponse) -> str:
    """One kind per endpoint+zone. State pages carry state-specific markup
    (e.g. class MHA-statename), so they cannot share a structure baseline."""
    path = raw.endpoint.split("://", 1)[-1].split("?")[0]
    zone = raw.meta.get("zone") or raw.meta.get("state_code") or ""
    return f"{path}|{zone}" if zone else path


def check_drift(conn: psycopg.Connection, raws: list[RawResponse]) -> list[str]:
    """Upsert structure hashes; return drift warnings (new hash where one existed)."""
    warnings: list[str] = []
    seen: set[tuple[str, str, str]] = set()
    for raw in raws:
        h = structure_hash(raw)
        if h is None:
            continue
        key = (raw.source, kind_of(raw), h)
        if key in seen:
            continue
        seen.add(key)
        source, kind, _ = key
        # race-safe upsert (cron ticks can overlap manual runs);
        # xmax = 0 distinguishes a fresh insert from a conflict-update
        inserted = conn.execute(
            """
            INSERT INTO schema_hashes (source, kind, structure_hash) VALUES (%s,%s,%s)
            ON CONFLICT (source, kind, structure_hash) DO UPDATE SET last_seen = now()
            RETURNING (xmax = 0) AS inserted
            """,
            (source, kind, h),
        ).fetchone()[0]
        if inserted:
            others = conn.execute(
                "SELECT count(*) FROM schema_hashes WHERE source=%s AND kind=%s AND structure_hash<>%s",
                (source, kind, h),
            ).fetchone()[0]
            if others:  # first hash for a kind is baseline, not drift
                msg = f"SCHEMA DRIFT {source} {kind}: new structure {h[:12]}…"
                warnings.append(msg)
                print(msg, file=sys.stderr)
    return warnings
