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
    "CHHATISGARH": "IN-CG",                      # dgr2's spelling
    "DELHI": "IN-DL", "GOA": "IN-GA", "GUJARAT": "IN-GJ", "HARYANA": "IN-HR",
    "HIMACHAL PRADESH": "IN-HP", "JAMMU AND KASHMIR": "IN-JK",
    "JAMMU & KASHMIR": "IN-JK", "LADAKH": "IN-JK",  # one shape on our map
    "JHARKHAND": "IN-JH", "KARNATAKA": "IN-KA",
    "KERALA": "IN-KL", "MADHYA PRADESH": "IN-MP", "MAHARASHTRA": "IN-MH",
    "MANIPUR": "IN-MN", "MEGHALAYA": "IN-ML", "MIZORAM": "IN-MZ",
    "NAGALAND": "IN-NL", "ODISHA": "IN-OD", "PUDUCHERRY": "IN-PY",
    "PUNJAB": "IN-PB", "RAJASTHAN": "IN-RJ", "SIKKIM": "IN-SK",
    "TAMIL NADU": "IN-TN", "TELANGANA": "IN-TS", "TRIPURA": "IN-TR",
    "UTTAR PRADESH": "IN-UP", "UTTARAKHAND": "IN-UK", "WEST BENGAL": "IN-WB",
}



def header_zone(upper: str, next_upper: str) -> tuple[bool, str | None]:
    """dgr2 prints each state's name on its own row with its STATE TOTAL right
    under it. A header we can't name (Bhutan's imports, the island grids, a new
    spelling) must still end the previous state, or its stations are silently
    credited to whichever state came before — which is how Chhattisgarh's coal
    ended up in Uttar Pradesh until 'CHHATISGARH' was added above."""
    if upper in STATE_NAMES:
        return True, STATE_NAMES[upper]
    return next_upper == "STATE TOTAL", None


TYPE_FUEL = {
    "THERMAL": "coal", "LIGNITE": "coal",
    "THER (GT)": "gas", "THER(GT)": "gas", "GAS": "gas",
    "THER (DG)": "oil", "THER(DG)": "oil", "DIESEL": "oil",
    "NUCLEAR": "nuclear", "HYDRO": "hydro",
}

# Headers that are deliberately not a zone on our map: Bhutan's hydro is an
# import, and the island grids aren't connected to the mainland.
IGNORED_HEADERS = {"BHUTAN", "ANDAMAN & NICOBAR ISLANDS", "LAKSHADWEEP"}

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
    unnamed: set[str] = set()
    zone = sector = None
    for r in range(sh.nrows):
        head = cell(r, 0)
        if not head:
            continue
        upper = head.upper()
        nxt = cell(r + 1, 0).upper() if r + 1 < sh.nrows else ""
        is_header, z = header_zone(upper, nxt)
        if is_header:
            zone, sector = z, None
            if z is None:
                unnamed.add(head)
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
    if unknown := unnamed - IGNORED_HEADERS:
        errors.append(f"unrecognised state headers (skipped): {sorted(unknown)}")
    return rows, errors


def station_key(zone: str, name: str) -> str:
    """Stable join key for a CEA station: zone + its name, case and punctuation
    folded. web/public/plants.json carries the same keys (gridscrapers.iced)."""
    return f"{zone}|{' '.join(re.sub(r'[^a-z0-9]+', ' ', name.lower()).split())}"


def outage_kind(remark: str) -> str:
    """The report's free-text reason, in four kinds that mean different things:
    a breakdown, planned work, a healthy unit nobody scheduled, or no fuel."""
    r = remark.lower()
    if re.search(r"reserve shut|\brsd\b|no schedule|low schedule|less schedule|backing down|low demand|economic", r):
        return "reserve"
    if re.search(r"coal|fuel|gas shortage|non.?availability of gas|gas not avail|shortage", r):
        return "fuel"
    if re.search(r"annual overhaul|capital overhaul|planned|maint|\baoh\b|\bcooh\b|r ?& ?m|renovation|inspection", r):
        return "planned"
    return "forced" if r else "unstated"


def parse_station_status(xls_bytes: bytes, as_of: date) -> list[dict]:
    """Station and unit rows: what was monitored, what was down, and why.

    Below each TYPE row the report lists stations (name, monitored MW, today's
    generation, capacity under outage) and under each station its units, one
    row per unit, with the outage start and expected return as Excel serial
    dates and a free-text remark. Hydro stations often carry an outage figure
    with no unit rows; that's kept at station level.
    """
    import xlrd

    wb = xlrd.open_workbook(file_contents=xls_bytes)
    sh = wb.sheet_by_index(0)

    def cell(r, c):
        return str(sh.cell_value(r, c)).strip()

    def num(r, c):
        v = sh.cell_value(r, c)
        return float(v) if isinstance(v, (int, float)) and v != "" else None

    def when(r, c):
        v = sh.cell_value(r, c)
        if isinstance(v, float) and v > 30000:
            return xlrd.xldate_as_datetime(v, wb.datemode).isoformat(timespec="minutes")
        return cell(r, c) or None

    stations: dict[str, dict] = {}
    zone = sector = fuel = None
    current = None
    for r in range(sh.nrows):
        head = cell(r, 0)
        if not head:
            continue
        upper = head.upper()
        nxt = cell(r + 1, 0).upper() if r + 1 < sh.nrows else ""
        is_header, z = header_zone(upper, nxt)
        if is_header:
            zone, sector, fuel, current = z, None, None, None
            continue
        if upper in ("STATE TOTAL",) or "REGION" in upper or upper.startswith("ALL INDIA"):
            current = None
            continue
        if "SECTOR" in upper and not any(ch.isdigit() for ch in upper):
            sector, current = SECTOR_NAMES.get(cell(r, 4).upper(), cell(r, 4) or "?"), None
            continue
        if upper.startswith("TYPE"):
            fuel, current = TYPE_FUEL.get(cell(r, 4).upper(), "other"), None
            continue
        if not (zone and fuel):
            continue
        if upper == "UNIT":
            if current is None:
                continue
            remark = cell(r, 17)
            out = num(r, 13) or 0.0
            current["units"].append({
                "unit": next((cell(r, c) for c in (1, 2, 3) if cell(r, c)), "").removesuffix(".0"), "mw": num(r, 7), "out_mw": out,
                "since": when(r, 14) if out else None, "expected": when(r, 16) if out else None,
                "remark": remark or None, "kind": outage_kind(remark) if out else None,
            })
            continue
        if num(r, 7) is None:
            continue
        key = station_key(zone, head)
        current = stations.setdefault(key, {
            "as_of": as_of, "zone": zone, "station": head, "station_key": key,
            "sector": sector, "fuel": fuel, "monitored_mw": 0.0, "outage_mw": 0.0,
            "actual_mu": 0.0, "units": [],
        })
        current["monitored_mw"] += num(r, 7) or 0.0
        current["outage_mw"] += num(r, 13) or 0.0
        current["actual_mu"] += num(r, 9) or 0.0
    return list(stations.values())


def store_station_status(conn: psycopg.Connection, stations: list[dict], raw_id) -> None:
    from psycopg.types.json import Jsonb

    for s in stations:
        conn.execute(
            """
            INSERT INTO station_status (as_of, zone, station, station_key, sector, fuel,
                monitored_mw, outage_mw, actual_mu, units, raw_id)
            VALUES (%(as_of)s,%(zone)s,%(station)s,%(station_key)s,%(sector)s,%(fuel)s,
                    %(monitored_mw)s,%(outage_mw)s,%(actual_mu)s,%(units)s,%(raw_id)s)
            ON CONFLICT (as_of, station_key) DO UPDATE SET
                monitored_mw=EXCLUDED.monitored_mw, outage_mw=EXCLUDED.outage_mw,
                actual_mu=EXCLUDED.actual_mu, units=EXCLUDED.units,
                raw_id=EXCLUDED.raw_id, inserted_at=now()
            """,
            s | {"units": Jsonb(s["units"]), "raw_id": raw_id},
        )


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
    return load_dgr2(conn, bytes(raw.body), day, raw_id)


def load_dgr2(conn: psycopg.Connection, body: bytes, day: date, raw_id, replace: bool = False) -> str | None:
    """Parse one dgr2 and store it. replace=True first drops the day's
    conventional rows, for reparsing an archived report after a parser fix
    (an upsert alone would leave rows the old parser put in the wrong state)."""
    try:
        rows, errors = parse_dgr2(body, day)
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
    if replace:
        conn.execute("DELETE FROM cea_state_energy WHERE as_of=%s AND sector <> 'RE'", (day,))
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
    # station/unit status rides along; a problem here mustn't lose the rows above
    try:
        with conn.transaction():
            stations = parse_station_status(body, day)
            store_station_status(conn, stations, raw_id)
        down = sum(s["outage_mw"] for s in stations)
        print(f"  [CEA] {day}: {len(stations)} stations, {down / 1000:.1f} GW under outage",
              file=sys.stderr)
    except Exception as e:
        print(f"  [CEA] {day}: station status not stored: {e}", file=sys.stderr)
    return None


def reparse(conn: psycopg.Connection) -> int:
    """Re-run the parser over every archived dgr2 (latest copy per day) and
    recompute that day's blend shares. No downloads."""
    days = conn.execute(
        """
        SELECT DISTINCT ON (meta->>'as_of') (meta->>'as_of')::date, id, body
        FROM raw_responses
        WHERE source=%s AND meta->>'kind'='dgr2' AND http_status=200 AND length(body) >= 5000
        ORDER BY meta->>'as_of', fetched_at DESC
        """, (SOURCE,)).fetchall()
    ok = 0
    for day, raw_id, body in days:
        err = load_dgr2(conn, bytes(body), day, raw_id, replace=True)
        if err:
            print(f"[CEA] {day}: {err}", file=sys.stderr)
            conn.rollback()
            continue
        compute_blend_shares(conn, day)
        conn.commit()
        ok += 1
    print(f"[CEA] reparsed {ok}/{len(days)} archived reports", file=sys.stderr)
    return ok


RE_URL = "https://gen-re.cea.gov.in/public/uploads/dailyReport/excel/Report-{iso}.xlsx"
RE_FUEL_COLS = {1: "wind", 2: "solar", 3: "res_nonsolar"}  # daily MU columns


def parse_re_report(xlsx_bytes: bytes, as_of: date) -> list[dict]:
    """gen-re.cea.gov.in daily RE report, sheet 'Generation': state-wise
    wind/solar/other-RE MU. Bilingual labels ('पंजाब / Punjab')."""
    import io

    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes), read_only=True)
    sh = wb["Generation"]
    rows = []
    for row in sh.iter_rows(values_only=True):
        label = str(row[0] or "")
        eng = label.split("/")[-1].strip().upper()
        zone = STATE_NAMES.get(eng)
        if not zone:
            continue
        for col, fuel in RE_FUEL_COLS.items():
            try:
                mu = float(row[col])
            except (TypeError, ValueError):
                continue
            rows.append({"zone": zone, "as_of": as_of, "sector": "RE", "fuel": fuel,
                         "capacity_mw": None, "program_mu": None, "actual_mu": mu})
    return rows


def ingest_re_day(conn: psycopg.Connection, client, day: date) -> str | None:
    raw = request_raw(client, SOURCE, "GET", RE_URL.format(iso=day.isoformat()),
                      meta={"kind": "re_report", "as_of": day.isoformat()})
    raw_id = archive_raw(conn, raw)
    if (raw.http_status or 0) != 200 or len(raw.body) < 5000:
        return f"RE download failed: status={raw.http_status}"
    try:
        rows = parse_re_report(bytes(raw.body), day)
    except Exception as e:
        conn.execute(
            "INSERT INTO psp_quarantine (source, as_of, raw_id, reason) VALUES (%s,%s,%s,%s)",
            (SOURCE, day, raw_id, f"RE parse crash: {e}"),
        )
        return f"RE parse crash: {e}"
    if len(rows) < 30:
        conn.execute(
            "INSERT INTO psp_quarantine (source, as_of, raw_id, reason) VALUES (%s,%s,%s,%s)",
            (SOURCE, day, raw_id, f"RE report suspiciously small: {len(rows)} rows"),
        )
        return "RE report too small"
    for row in rows:
        conn.execute(
            """
            INSERT INTO cea_state_energy (zone, as_of, sector, fuel, capacity_mw,
                program_mu, actual_mu, source, raw_id)
            VALUES (%(zone)s,%(as_of)s,%(sector)s,%(fuel)s,%(capacity_mw)s,
                    %(program_mu)s,%(actual_mu)s,%(src)s,%(raw_id)s)
            ON CONFLICT (zone, as_of, sector, fuel) DO UPDATE SET
                actual_mu=EXCLUDED.actual_mu, raw_id=EXCLUDED.raw_id, inserted_at=now()
            """,
            row | {"src": SOURCE, "raw_id": raw_id},
        )
    print(f"  [CEA-RE] {day}: {len(rows)} state×fuel rows", file=sys.stderr)
    return None


def compute_blend_shares(conn: psycopg.Connection, as_of: date) -> int:
    """basis='cea_blend_t1' for zones without recent PSP shares.

    Conventional split from dgr2 (all sectors); RE MU from the gen-re daily
    report. Describes in-state GENERATION mix (drawal unmodeled — unlike the
    PSP blend), match_rate NULL to mark that. docs/METHODOLOGY.md.
    """
    psp_zones = {z for (z,) in conn.execute(
        "SELECT DISTINCT zone FROM state_fuel_shares "
        "WHERE basis='psp_actual_t1' AND as_of >= %s - 2", (as_of,)
    ).fetchall()}
    rows = conn.execute(
        """
        SELECT zone, CASE WHEN sector='RE' THEN fuel ELSE fuel END AS fuel, sum(actual_mu)
        FROM cea_state_energy WHERE as_of = %s GROUP BY zone, 2
        """,
        (as_of,),
    ).fetchall()
    by_zone: dict[str, dict[str, float]] = {}
    for zone, fuel, mu in rows:
        if zone in psp_zones or not mu or mu <= 0:
            continue
        by_zone.setdefault(zone, {})[fuel] = mu
    n = 0
    for zone, fuels in by_zone.items():
        total = sum(fuels.values())
        if total < 1:  # under 1 MU/day of attributable generation: skip
            continue
        conn.execute("DELETE FROM state_fuel_shares WHERE zone=%s AND as_of=%s", (zone, as_of))
        for fuel, mu in fuels.items():
            share = mu / total
            if share < 0.0005:
                continue
            conn.execute(
                """INSERT INTO state_fuel_shares (zone, as_of, fuel, share, match_rate, basis)
                   VALUES (%s,%s,%s,%s,NULL,'cea_blend_t1')""",
                (zone, as_of, fuel, share),
            )
        n += 1
    return n


def latest_ingested(conn: psycopg.Connection) -> date | None:
    return conn.execute(
        "SELECT max(as_of) FROM cea_state_energy WHERE sector <> 'RE'"
    ).fetchone()[0]


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
            return
        re_err = ingest_re_day(conn, client, yesterday)
        if re_err:
            print(f"[CEA-RE] {yesterday}: {re_err}", file=sys.stderr)
        n = compute_blend_shares(conn, yesterday)
        print(f"[CEA] cea_blend_t1 shares for {n} zones", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", choices=["ingest", "reparse"])
    ap.add_argument("--backfill", type=int, default=1)
    args = ap.parse_args()
    if args.command == "reparse":
        with psycopg.connect(get_dsn()) as conn:
            return 0 if reparse(conn) else 1
    yesterday = (datetime.now(IST) - timedelta(days=1)).date()
    ok = 0
    with psycopg.connect(get_dsn()) as conn, make_client(legacy_tls=True) as client:
        # each day as the tick does it: conventional (dgr2), then renewables,
        # then that day's blended shares
        for i in range(args.backfill):
            day = yesterday - timedelta(days=i)
            if ingest_day(conn, client, day) is None:
                ok += 1
                re_err = ingest_re_day(conn, client, day)
                if re_err:
                    print(f"[CEA-RE] {day}: {re_err}", file=sys.stderr)
                else:
                    compute_blend_shares(conn, day)
            conn.commit()
            time.sleep(1.0)
    print(f"[CEA] ingested {ok}/{args.backfill}", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
