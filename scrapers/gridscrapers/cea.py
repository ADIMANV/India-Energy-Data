"""CEA/NPP daily generation report (dgr2) — national state×sector×fuel MU.

    python -m gridscrapers.cea ingest [--backfill N]

URL pattern (recon 2026-06-12):
    npp.gov.in/public-reports/cea/daily/dgr/DD-MM-YYYY/dgr2-YYYY-MM-DD.xls
Legacy .xls (xlrd), hierarchical outline: REGION → STATE → SECTOR → TYPE:
(fuel aggregate, what we store) → station → unit rows. Covers conventional
utility stations in ALL regions (no solar/wind aggregation here).

Validation: STATE TOTAL vs sum of its TYPE rows ±2% → psp_quarantine.
"""

import argparse
import io
import re
import sys
import time
from datetime import date, datetime, timedelta

import psycopg

from .db import archive_raw, get_dsn
from .http import IST, make_client, request_raw
from .schema import RawResponse

SOURCE = "cea_dgr"
PARSER_VERSION = 1
URL = "https://npp.gov.in/public-reports/cea/daily/dgr/{d}/dgr2-{iso}.xls"
TOLERANCE = 0.02

STATE_NAMES = {
    "ANDHRA PRADESH": "IN-AP", "ARUNACHAL PRADESH": "IN-AR", "ASSAM": "IN-AS",
    "BIHAR": "IN-BR", "CHHATTISGARH": "IN-CG", "CHATTISGARH": "IN-CG",
    "DELHI": "IN-DL", "GOA": "IN-GA", "GUJARAT": "IN-GJ", "HARYANA": "IN-HR",
    "HIMACHAL PRADESH": "IN-HP", "JAMMU AND KASHMIR": "IN-JK",
    "JAMMU & KASHMIR": "IN-JK", "JHARKHAND": "IN-JH", "KARNATAKA": "IN-KA",
    "KERALA": "IN-KL", "MADHYA PRADESH": "IN-MP", "MAHARASHTRA": "IN-MH",
    "MANIPUR": "IN-MN", "MEGHALAYA": "IN-ML", "MIZORAM": "IN-MZ",
    "NAGALAND": "IN-NL", "ODISHA": "IN-OD", "PUDUCHERRY": "IN-PY",
    "PUNJAB": "IN-PB", "RAJASTHAN": "IN-RJ", "SIKKIM": "IN-SK",
    "TAMIL NADU": "IN-TN", "TELANGANA": "IN-TS", "TRIPURA": "IN-TR",
    "UTTAR PRADESH": "IN-UP", "UTTARAKHAND": "IN-UK", "WEST BENGAL": "IN-WB",
}

TYPE_FUEL = {
    "THERMAL": "coal", "LIGNITE": "coal",
    "THER (GT)": "gas", "THER(GT)": "gas", "GAS": "gas",
    "THER (DG)": "oil", "THER(DG)": "oil", "DIESEL": "oil",
    "NUCLEAR": "nuclear", "HYDRO": "hydro",
}

SECTOR_NAMES = {"STATE SECTOR": "STATE", "PVT SECTOR": "PVT", "CENTRAL SECTOR": "CENTRAL"}


def dgr_url(day: date) -> str:
    return URL.format(d=day.strftime("%d-%m-%Y"), iso=day.isoformat())


def parse_dgr2(xls_bytes: bytes, as_of: date) -> tuple[list[dict], list[str]]:
    """Returns (TYPE-row aggregates, validation errors)."""
    import xlrd

    wb = xlrd.open_workbook(file_contents=xls_bytes)
    sh = wb.sheet_by_index(0)

    def cell(r, c):
        return str(sh.cell_value(r, c)).strip()

    def num(r, c):
        v = sh.cell_value(r, c)
        return float(v) if isinstance(v, (int, float)) else None

    rows: list[dict] = []
    state_totals: dict[str, float] = {}
    zone = sector = None
    for r in range(sh.nrows):
        head = cell(r, 0)
        if not head:
            continue
        upper = head.upper()
        if upper in STATE_NAMES:
            zone, sector = STATE_NAMES[upper], None
            continue
        if upper == "STATE TOTAL" and zone:
            # the report repeats the state hierarchy per section (thermal,
            # hydro, ...) — totals accumulate across sections
            if (v := num(r, 9)) is not None:
                state_totals[zone] = state_totals.get(zone, 0) + v
            continue
        if "SECTOR" in upper and not any(ch.isdigit() for ch in upper):
            sector = SECTOR_NAMES.get(cell(r, 4).upper(), cell(r, 4) or "?")
            continue
        if upper.startswith("TYPE"):
            tname = cell(r, 4).upper()
            fuel = TYPE_FUEL.get(tname, "other")
            if zone and sector:
                rows.append({
                    "zone": zone, "as_of": as_of, "sector": sector, "fuel": fuel,
                    "capacity_mw": num(r, 7), "program_mu": num(r, 8),
                    "actual_mu": num(r, 9),
                })

    errors = []
    by_zone: dict[str, float] = {}
    for row in rows:
        by_zone[row["zone"]] = by_zone.get(row["zone"], 0) + (row["actual_mu"] or 0)
    for z, total in state_totals.items():
        got = by_zone.get(z, 0)
        if abs(got - total) > max(TOLERANCE * abs(total), 0.5):
            errors.append(f"{z}: TYPE sum {got:.2f} vs STATE TOTAL {total:.2f}")
    return rows, errors


def ingest_day(conn: psycopg.Connection, client, day: date, registry=None) -> str | None:
    raw = request_raw(client, SOURCE, "GET", dgr_url(day),
                      meta={"kind": "dgr2", "as_of": day.isoformat()})
    raw_id = archive_raw(conn, raw)
    if (raw.http_status or 0) != 200 or len(raw.body) < 5000:
        conn.execute(
            "INSERT INTO psp_quarantine (source, as_of, raw_id, reason) VALUES (%s,%s,%s,%s)",
            (SOURCE, day, raw_id, f"download failed: status={raw.http_status}"),
        )
        return "download failed"
    try:
        rows, errors = parse_dgr2(bytes(raw.body), day)
    except Exception as e:
        conn.execute(
            "INSERT INTO psp_quarantine (source, as_of, raw_id, reason) VALUES (%s,%s,%s,%s)",
            (SOURCE, day, raw_id, f"parse crash: {e}"),
        )
        return f"parse crash: {e}"
    if errors:
        conn.execute(
            "INSERT INTO psp_quarantine (source, as_of, raw_id, reason) VALUES (%s,%s,%s,%s)",
            (SOURCE, day, raw_id, "; ".join(errors)[:1000]),
        )
        return "; ".join(errors)
    for row in rows:
        conn.execute(
            """
            INSERT INTO cea_state_energy (zone, as_of, sector, fuel, capacity_mw,
                program_mu, actual_mu, source, raw_id)
            VALUES (%(zone)s,%(as_of)s,%(sector)s,%(fuel)s,%(capacity_mw)s,
                    %(program_mu)s,%(actual_mu)s,%(src)s,%(raw_id)s)
            ON CONFLICT (zone, as_of, sector, fuel) DO UPDATE SET
                capacity_mw=EXCLUDED.capacity_mw, program_mu=EXCLUDED.program_mu,
                actual_mu=EXCLUDED.actual_mu, raw_id=EXCLUDED.raw_id, inserted_at=now()
            """,
            row | {"src": SOURCE, "raw_id": raw_id},
        )
    print(f"  [CEA] {day}: {len(rows)} state×sector×fuel rows", file=sys.stderr)
    return None


def latest_ingested(conn: psycopg.Connection) -> date | None:
    return conn.execute("SELECT max(as_of) FROM cea_state_energy").fetchone()[0]


def ensure_current(conn: psycopg.Connection) -> None:
    """Tick hook: ingest T-1 dgr2 if missing (no-op once ingested).

    NPP publishes dgr2 late morning IST; back off 2h between attempts so an
    unpublished report doesn't add a quarantine row every 15-min tick.
    """
    yesterday = (datetime.now(IST) - timedelta(days=1)).date()
    latest = latest_ingested(conn)
    if latest is not None and latest >= yesterday:
        return
    recent_attempt = conn.execute(
        "SELECT 1 FROM psp_quarantine WHERE source=%s AND as_of=%s "
        "AND created_at > now() - interval '2 hours' LIMIT 1",
        (SOURCE, yesterday),
    ).fetchone()
    if recent_attempt:
        return
    with make_client(legacy_tls=True) as client:
        err = ingest_day(conn, client, yesterday)
        if err:
            print(f"[CEA] {yesterday}: {err}", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", choices=["ingest"])
    ap.add_argument("--backfill", type=int, default=1)
    args = ap.parse_args()
    yesterday = (datetime.now(IST) - timedelta(days=1)).date()
    ok = 0
    with psycopg.connect(get_dsn()) as conn, make_client(legacy_tls=True) as client:
        for i in range(args.backfill):
            if ingest_day(conn, client, yesterday - timedelta(days=i)) is None:
                ok += 1
            conn.commit()
            time.sleep(1.0)
    print(f"[CEA] ingested {ok}/{args.backfill}", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
