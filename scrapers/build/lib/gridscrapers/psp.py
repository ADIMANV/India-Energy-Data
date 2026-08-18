"""RLDC daily PSP reports (PDF) — measured T-1 state energy by fuel.

    python -m gridscrapers.psp ingest [--region NR|SR] [--backfill N]
    python -m gridscrapers.psp shares [--region NR|SR] [--date YYYY-MM-DD]

Regions:
  NR (nrldc.in)  — DataTables listing API → download-file links (XHR header)
  SR (srldc.in)  — direct date-pattern URLs var/ftp/reports/psp/YYYY/MonYY/DD-MM-YYYY-psp.pdf
  WR/ER/NER      — pending (JS-routed docs page / login portal / dead public DNS;
                   probe from the VPS, see docs/sources/README.md)

PDF bytes are archived to raw_responses BEFORE parsing. Parsed into
daily_state_energy (2A + 2C peak) and station_daily (3A state + 3B central).
Validation ±2% (state fuel sum vs printed total; region/Total row vs state
sum); failures → psp_quarantine, raw kept.

Share calibration (basis='psp_actual_t1', docs/METHODOLOGY.md): consumption
mix = own generation by fuel + actual drawal × regional central mix (3B),
scaled by how much of total drawal the central pool covers; the uncovered
remainder (inter-regional/PX) goes to 'other'.
"""

import argparse
import io
import json
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Callable

import psycopg

from .db import archive_raw, get_dsn
from .http import IST, make_client, request_raw
from .schema import RawResponse

PARSER_VERSION = 2
TOTAL_TOLERANCE = 0.02

NUM = re.compile(r"^-?[\d,]+(?:\.\d+)?$")
TIME = re.compile(r"^\d{1,2}:\d{2}(?::\d{2})?$")

FUEL_SUFFIX = [  # substring matches: PDF names come glued ('BHAKRAHPS')
    (re.compile(r"SOLAR", re.I), "solar"),
    (re.compile(r"WIND", re.I), "wind"),
    (re.compile(r"BIOMASS|CO-?GEN|BAGASSE", re.I), "biomass"),
    (re.compile(r"GPS|CCGT|GAS|GT-|NAPTHA|DIESEL", re.I), "gas"),
    (re.compile(r"HPS|HEP\b|HYDRO|HYDEL|SHP\b|DAM\b|PH\b", re.I), "hydro"),
    (re.compile(r"NAPS|RAPS|RAPP|MAPS|KAIGA|KKNPP|ATOMIC|NUCLEAR", re.I), "nuclear"),
    (re.compile(r"TPS|STPS|TPP|THERMAL|LIGNITE|\bTS\b", re.I), "coal"),
    # central RE SPVs are overwhelmingly solar parks; registry match wins
    # when the name survives PDF mangling
    (re.compile(r"ACME|ADANIGREEN|RENEW|SECI|GREENENERGY|SPV", re.I), "solar"),
]

_NOT_A_STATION = re.compile(
    r"StateControlArea|RegionalEntities|GrossGen|NetGen|3\(B\)|Generation Summary|^ISGS$"
    r"|Exchange|Import|Export",  # inter-regional summary blocks share the page
    re.I,
)
_HDR = re.compile(
    r"^(Inst\.?Capacity|Inst\.?Min|\(06:00|Station/|\(MW\)|Gen\(MU\)|EveningPeak|NIL|"
    r"19:00|20:00|03:00|Gross\(MU\)|ISGS$)"
)


@dataclass(frozen=True)
class RegionCfg:
    source: str
    region: str
    state_map: dict[str, str]
    non_state: tuple = ("RAILWAYS", "BULKCONSUMER", "REGION", "TOTAL")
    # where NetMU/AvgMW sit in central (3B) rows, from the right
    central_net_idx: int = -2
    central_avg_idx: int = -1
    # False = 3B layout not yet trustworthy: skip central station rows and
    # blend shares without a central pool (uncovered drawal → 'other')
    central_reliable: bool = True


NRLDC = RegionCfg(
    source="psp_nrldc",
    region="NR",
    state_map={
        "PUNJAB": "IN-PB", "HARYANA": "IN-HR", "RAJASTHAN": "IN-RJ", "DELHI": "IN-DL",
        "UTTARPRADESH": "IN-UP", "UP": "IN-UP", "UTTARAKHAND": "IN-UK",
        "HIMACHALPRADESH": "IN-HP", "HP": "IN-HP", "CHANDIGARH": "IN-CH",
        "JKUTLADAKHUT": "IN-JK", "JKUTLAD": "IN-JK",
    },
    # NR 3B tail: SCHD Gross Net AGC AvgMW UI
    central_net_idx=-4,
    central_avg_idx=-2,
)

SRLDC = RegionCfg(
    source="psp_srldc",
    region="SR",
    state_map={
        "ANDHRAPRADESH": "IN-AP", "KARNATAKA": "IN-KA", "KERALA": "IN-KL",
        "PUDUCHERRY": "IN-PY", "TAMILNADU": "IN-TN", "TELANGANA": "IN-TS",
    },
    # SR 3B tail: Gross Net AvgMW (same as 3A)
)

WRLDC = RegionCfg(
    source="psp_wrldc",
    region="WR",
    state_map={
        "GUJARAT": "IN-GJ", "MAHARASHTRA": "IN-MH", "MADHYAPRADESH": "IN-MP",
        "CHHATTISGARH": "IN-CG", "GOA": "IN-GA",
    },
    # WR 2A includes embedded industrial control areas + DD/DNH discom rows
    non_state=("RAILWAYS", "BULKCONSUMER", "REGION", "TOTAL",
               "BALCO", "AMNSIL", "DNHDDPDCL", "RILJAMNAGAR", "NPCIL"),
    # WR 3B mixes a second RE/state-area listing (MW tails) and ISGS/IPP
    # aggregate rows into the same section — net-MU extraction unsafe until
    # that layout is mapped; shares blend without the central pool
    central_reliable=False,
)

REGIONS = {"NR": NRLDC, "SR": SRLDC, "WR": WRLDC}


def _norm(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", s.upper())


def _zone_for(name: str, cfg: RegionCfg) -> str | None:
    n = _norm(name)
    if not n or any(n.startswith(x) for x in cfg.non_state):
        return None
    for key, zone in cfg.state_map.items():
        if n.startswith(key) or key.startswith(n):
            return zone
    return None


def _f(tok: str) -> float:
    return float(tok.replace(",", ""))


def extract_pages(pdf_bytes: bytes) -> list[str]:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return [p.extract_text() or "" for p in pdf.pages]


def report_date(text: str) -> date:
    m = re.search(r"For\s*(\d{1,2}-[A-Za-z]{3}-\d{4})", text)
    if not m:
        raise ValueError("report date not found")
    return datetime.strptime(m.group(1), "%d-%b-%Y").date()


def _section(text: str, start: str, end: str) -> str:
    i = text.find(start)
    j = text.find(end, i + 1)
    if i == -1:
        raise ValueError(f"section {start!r} not found")
    return text[i:j] if j != -1 else text[i:]


def _split_line(line: str) -> tuple[list[str], list[float], list[str]]:
    toks = line.split()
    name_toks: list[str] = []
    for t in toks:
        if NUM.match(t):
            break
        name_toks.append(t)
    nums = [_f(t) for t in toks[len(name_toks):] if NUM.match(t)]
    times = [t for t in toks if TIME.match(t)]
    return name_toks, nums, times


def _resolve_name(name_toks: list[str], pending: list[str], cfg: RegionCfg) -> tuple[str | None, str]:
    """Data line's own tokens first; stray tokens from the previous line
    ('Diesel etc.)', 'Ladakh(UT)') must not poison the state name."""
    for cand in (name_toks, pending + name_toks):
        name = " ".join(cand)
        zone = _zone_for(name, cfg)
        if zone:
            return zone, name
    return None, " ".join(pending + name_toks)


def _row_common(zone, name, cfg):
    return {"name": name, "zone": zone,
            "is_region": _norm(name).startswith(("REGION", "TOTAL"))}


def parse_2a(text: str, cfg: RegionCfg) -> list[dict]:
    """State fuel energy (MU). NR: 13 numbers; SR: 12 (different fuel order)."""
    sec = _section(text, "2(A)", "2(B)")
    out: list[dict] = []
    pending: list[str] = []
    n_expected = {"NR": 13, "SR": 12, "WR": 14}[cfg.region]
    for line in sec.splitlines()[1:]:
        name_toks, nums, _ = _split_line(line)
        if not line.split():
            continue
        if len(nums) == n_expected:
            zone, name = _resolve_name(name_toks, pending, cfg)
            pending = []
            n = nums
            if cfg.region == "NR":
                # THERMAL HYDRO GAS SOLAR WIND OTHERS TOTAL SCH ACT UI REQ SHORT CONS
                row = {
                    "thermal_mu": n[0], "hydro_mu": n[1], "gas_mu": n[2], "solar_mu": n[3],
                    "wind_mu": n[4], "others_mu": n[5], "total_gen_mu": n[6],
                    "drawal_sch_mu": n[7], "act_drawal_mu": n[8], "ui_mu": n[9],
                    "requirement_mu": n[10], "shortage_mu": n[11], "consumption_mu": n[12],
                }
            elif cfg.region == "SR":
                # THERMAL HYDRO GAS WIND SOLAR OTHERS SCH ACT UI AVAIL DEMANDMET SHORT
                row = {
                    "thermal_mu": n[0], "hydro_mu": n[1], "gas_mu": n[2], "wind_mu": n[3],
                    "solar_mu": n[4], "others_mu": n[5],
                    "total_gen_mu": round(sum(n[0:6]), 3),
                    "drawal_sch_mu": n[6], "act_drawal_mu": n[7], "ui_mu": n[8],
                    "requirement_mu": n[9], "consumption_mu": n[10], "shortage_mu": n[11],
                }
            else:
                # WR: THERMAL HYDRO GAS WIND SOLAR OTHERS TOTAL SCH ACT UI AVAIL DM SHORT CONS
                # (wind before solar verified: CG row has 0 wind / 5.3 solar)
                row = {
                    "thermal_mu": n[0], "hydro_mu": n[1], "gas_mu": n[2], "wind_mu": n[3],
                    "solar_mu": n[4], "others_mu": n[5], "total_gen_mu": n[6],
                    "drawal_sch_mu": n[7], "act_drawal_mu": n[8], "ui_mu": n[9],
                    "requirement_mu": n[10], "shortage_mu": n[12], "consumption_mu": n[13],
                }
            out.append(_row_common(zone, name, cfg) | row)
        elif not nums:
            pending = name_toks
    return out


def parse_2c(text: str, cfg: RegionCfg) -> dict[str, tuple[float, str]]:
    """zone -> (max demand met MW, time)."""
    sec = _section(text, "2(C)", "3(A)")
    out: dict[str, tuple[float, str]] = {}
    for line in sec.splitlines():
        toks = line.split()
        times = [t for t in toks if TIME.match(t)]
        if len(times) < 2:
            continue
        name_toks, nums, _ = _split_line(line)
        first_time = next((t for t in toks if TIME.match(t)), None)
        zone = _zone_for(" ".join(name_toks), cfg)
        if zone and nums and zone not in out:
            out[zone] = (nums[0], first_time)
    return out


def station_fuel(name: str, registry: list[tuple] | None) -> tuple[str | None, int | None]:
    if registry:
        from .fuelmix import _score, MATCH_THRESHOLD

        best, bs = None, 0.0
        for pid, pname, pfuel in registry:
            s = _score(name, pname)
            if s > bs:
                best, bs = (pid, pfuel), s
        if best and bs >= MATCH_THRESHOLD:
            return best[1], best[0]
    for pat, fuel in FUEL_SUFFIX:
        if pat.search(name):
            return fuel, None
    return None, None


def parse_stations(text: str, cfg: RegionCfg, registry: list[tuple] | None = None) -> list[dict]:
    """3A (per state) + 3B (central, zone IN-<region>)."""
    sec = _section(text, "3(A)", "4(A)")
    central = sec.find("3(B)")
    out: list[dict] = []
    for is_central, chunk in ((False, sec[:central]), (True, sec[central:])):
        if is_central and not cfg.central_reliable:
            continue
        zone = f"IN-{cfg.region}" if is_central else None
        pending: list[str] = []
        for line in chunk.splitlines():
            line = line.strip()
            if not line or _HDR.match(line.replace(" ", "")):
                continue
            if re.match(r"^(Sub-?)?Total", line, re.I):
                pending = []
                continue
            if not any(ch.isdigit() for ch in line):
                z = _zone_for(line, cfg)
                if z and not is_central:
                    zone = z
                    pending = []
                    continue
                # embedded control areas (BALCO, AMNSIL, RIL Jamnagar...) own
                # sections in 3A — stop attributing rows to the previous state
                if not is_central and any(_norm(line).startswith(x) for x in cfg.non_state):
                    zone = None
                    pending = []
                    continue
            name_toks, nums, times = _split_line(line)
            toks = line.split()
            if len(nums) < 4 or zone is None:
                pending = pending + name_toks if not nums else []
                continue
            name = " ".join(pending + name_toks).strip()
            pending = []
            if not name or _NOT_A_STATION.search(name):
                continue
            day_peak = None
            if times:  # number immediately before the first time token = day peak
                idx = toks.index(times[0])
                if NUM.match(toks[idx - 1]):
                    day_peak = _f(toks[idx - 1])
            if is_central:
                net_i, avg_i = cfg.central_net_idx, cfg.central_avg_idx
            else:
                net_i, avg_i = -2, -1
            enough = len(nums) >= max(5, abs(net_i) + 1)
            fuel, plant_id = station_fuel(name, registry)
            out.append({
                "zone": zone, "station_raw": name, "fuel": fuel, "plant_id": plant_id,
                "inst_capacity_mw": nums[0], "day_peak_mw": day_peak,
                "day_energy_net_mu": nums[net_i] if enough else None,
                "avg_mw": nums[avg_i] if enough else None,
            })
    return out


def validate(states: list[dict]) -> list[str]:
    errors = []
    fuels = ["thermal_mu", "hydro_mu", "gas_mu", "solar_mu", "wind_mu", "others_mu"]
    region_row = None
    for r in states:
        fuel_sum = sum(r[f] or 0 for f in fuels)
        total = r["total_gen_mu"] or 0
        if abs(fuel_sum - total) > max(TOTAL_TOLERANCE * abs(total), 0.5):
            errors.append(f"{r['name']}: fuel sum {fuel_sum:.2f} vs total {total:.2f}")
        if r["is_region"]:
            region_row = r
    if region_row:
        state_sum = sum(r["total_gen_mu"] or 0 for r in states if not r["is_region"])
        if abs(state_sum - region_row["total_gen_mu"]) > TOTAL_TOLERANCE * region_row["total_gen_mu"]:
            errors.append(
                f"region total {region_row['total_gen_mu']:.1f} vs state sum {state_sum:.1f}"
            )
    return errors


def parse_report(pdf_bytes: bytes, registry: list[tuple] | None = None,
                 cfg: RegionCfg = NRLDC) -> dict:
    pages = extract_pages(pdf_bytes)
    text = "\n".join(pages)
    as_of = report_date(text)
    states = parse_2a(text, cfg)
    peaks = parse_2c(text, cfg)
    stations = parse_stations(text, cfg, registry)
    for r in states:
        if r["zone"] and r["zone"] in peaks:
            r["peak_demand_met_mw"], r["peak_time"] = peaks[r["zone"]]
    return {"as_of": as_of, "states": states, "stations": stations,
            "errors": validate(states)}


# ---------------------------------------------------------------- discovery

def discover_nr(client, length: int = 100, start: int = 0) -> list[dict]:
    raw = request_raw(
        client, NRLDC.source, "GET",
        f"https://nrldc.in/get-documents-list/111?draw=1&start={start}&length={length}",
        meta={"kind": "listing"},
    )
    if (raw.http_status or 0) != 200:
        raise RuntimeError(f"NR listing failed: {raw.http_status} {raw.meta.get('error')}")
    docs = []
    for row in json.loads(raw.body)["data"]:
        m = re.search(r"href='([^']+)'", row.get("download", ""))
        if m:
            docs.append({"title": row["title"], "url": m.group(1).replace("&amp;", "&")})
    return docs


def sr_url(day: date) -> str:
    return (f"https://srldc.in/var/ftp/reports/psp/{day.year}/"
            f"{day.strftime('%b%y')}/{day.strftime('%d-%m-%Y')}-psp.pdf")


def wr_url(day: date) -> str:
    # IIS directory tree, archives back to 2018
    return (f"https://reporting.wrldc.in:8081/PSP/{day.year}/"
            f"{day.strftime('%B')}/WRLDC_PSP_Report_{day.strftime('%d-%m-%Y')}.pdf")


def report_urls(client, cfg: RegionCfg, n: int) -> list[dict]:
    """Most-recent-first report URLs for a region."""
    if cfg.region == "NR":
        return discover_nr(client, length=max(n, 10))[:n]
    url_fn = {"SR": sr_url, "WR": wr_url}[cfg.region]
    yesterday = (datetime.now(IST) - timedelta(days=1)).date()
    return [{"title": f"{cfg.region.lower()}-psp-{d}", "url": url_fn(d)}
            for d in (yesterday - timedelta(days=i) for i in range(n))]


# ---------------------------------------------------------------- ingestion

def ingest_pdf(conn: psycopg.Connection, raw: RawResponse, registry,
               cfg: RegionCfg) -> tuple[date | None, str | None]:
    raw_id = archive_raw(conn, raw)
    if (raw.http_status or 0) != 200 or not raw.body.startswith(b"%PDF"):
        conn.execute(
            "INSERT INTO psp_quarantine (source, raw_id, reason) VALUES (%s,%s,%s)",
            (cfg.source, raw_id, f"download failed: status={raw.http_status}"),
        )
        return None, "download failed"
    try:
        parsed = parse_report(bytes(raw.body), registry, cfg)
    except Exception as e:
        conn.execute(
            "INSERT INTO psp_quarantine (source, raw_id, reason) VALUES (%s,%s,%s)",
            (cfg.source, raw_id, f"parse crash: {e}"),
        )
        return None, f"parse crash: {e}"
    as_of = parsed["as_of"]
    if parsed["errors"]:
        conn.execute(
            "INSERT INTO psp_quarantine (source, as_of, raw_id, reason) VALUES (%s,%s,%s,%s)",
            (cfg.source, as_of, raw_id, "; ".join(parsed["errors"])[:1000]),
        )
        return as_of, "; ".join(parsed["errors"])

    n_states = 0
    for r in parsed["states"]:
        if not r["zone"]:
            continue
        conn.execute(
            """
            INSERT INTO daily_state_energy (zone, as_of, region, thermal_mu, hydro_mu, gas_mu,
                solar_mu, wind_mu, others_mu, total_gen_mu, drawal_sch_mu, act_drawal_mu, ui_mu,
                requirement_mu, shortage_mu, consumption_mu, peak_demand_met_mw, peak_time,
                source, raw_id, parser_version)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (zone, as_of) DO UPDATE SET
                thermal_mu=EXCLUDED.thermal_mu, hydro_mu=EXCLUDED.hydro_mu,
                gas_mu=EXCLUDED.gas_mu, solar_mu=EXCLUDED.solar_mu, wind_mu=EXCLUDED.wind_mu,
                others_mu=EXCLUDED.others_mu, total_gen_mu=EXCLUDED.total_gen_mu,
                drawal_sch_mu=EXCLUDED.drawal_sch_mu, act_drawal_mu=EXCLUDED.act_drawal_mu,
                ui_mu=EXCLUDED.ui_mu, requirement_mu=EXCLUDED.requirement_mu,
                shortage_mu=EXCLUDED.shortage_mu, consumption_mu=EXCLUDED.consumption_mu,
                peak_demand_met_mw=EXCLUDED.peak_demand_met_mw, peak_time=EXCLUDED.peak_time,
                raw_id=EXCLUDED.raw_id, parser_version=EXCLUDED.parser_version, inserted_at=now()
            """,
            (r["zone"], as_of, cfg.region, r["thermal_mu"], r["hydro_mu"], r["gas_mu"],
             r["solar_mu"], r["wind_mu"], r["others_mu"], r["total_gen_mu"],
             r["drawal_sch_mu"], r["act_drawal_mu"], r["ui_mu"], r["requirement_mu"],
             r["shortage_mu"], r["consumption_mu"], r.get("peak_demand_met_mw"),
             r.get("peak_time"), cfg.source, raw_id, PARSER_VERSION),
        )
        n_states += 1
    for s in parsed["stations"]:
        conn.execute(
            """
            INSERT INTO station_daily (zone, as_of, station_raw, fuel, inst_capacity_mw,
                day_peak_mw, day_energy_net_mu, avg_mw, plant_id, source, raw_id)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (zone, as_of, station_raw) DO UPDATE SET
                fuel=EXCLUDED.fuel, inst_capacity_mw=EXCLUDED.inst_capacity_mw,
                day_peak_mw=EXCLUDED.day_peak_mw, day_energy_net_mu=EXCLUDED.day_energy_net_mu,
                avg_mw=EXCLUDED.avg_mw, plant_id=EXCLUDED.plant_id, raw_id=EXCLUDED.raw_id
            """,
            (s["zone"], as_of, s["station_raw"], s["fuel"], s["inst_capacity_mw"],
             s["day_peak_mw"], s["day_energy_net_mu"], s["avg_mw"], s["plant_id"],
             cfg.source, raw_id),
        )
    print(f"  [{cfg.region}] {as_of}: {n_states} states, {len(parsed['stations'])} stations",
          file=sys.stderr)
    return as_of, None


def compute_psp_shares(conn: psycopg.Connection, as_of: date, cfg: RegionCfg) -> int:
    central = conn.execute(
        """
        SELECT coalesce(fuel, 'other'), sum(day_energy_net_mu)
        FROM station_daily
        WHERE zone = %s AND as_of = %s AND day_energy_net_mu > 0
        GROUP BY 1
        """,
        (f"IN-{cfg.region}", as_of),
    ).fetchall()
    central_total = sum(v for _, v in central) or 1.0
    central_mix = {f: v / central_total for f, v in central}
    central_known = sum(v for f, v in central_mix.items() if f != "other")

    rows = conn.execute(
        "SELECT zone, thermal_mu, hydro_mu, gas_mu, solar_mu, wind_mu, others_mu, act_drawal_mu "
        "FROM daily_state_energy WHERE as_of = %s AND source = %s",
        (as_of, cfg.source),
    ).fetchall()
    # the regional central pool only covers part of total drawal; the rest is
    # inter-regional/PX energy of unknown (mostly thermal) origin → 'other'
    total_drawal = sum(max(r[7] or 0, 0) for r in rows)
    coverage = min(1.0, central_total / total_drawal) if total_drawal > 0 else 0.0
    n = 0
    for zone, th, hy, gas, sol, wnd, oth, drawal in rows:
        own = {"coal": th or 0, "hydro": hy or 0, "gas": gas or 0,
               "solar": sol or 0, "wind": wnd or 0, "biomass": oth or 0}
        drawal = max(drawal or 0, 0)  # net exporters: consumption mix ≈ own mix
        covered = drawal * coverage
        blended = {f: v + covered * central_mix.get(f, 0) for f, v in own.items()}
        blended["other"] = covered * central_mix.get("other", 0) + (drawal - covered)
        total = sum(blended.values())
        if total <= 0:
            continue
        conn.execute("DELETE FROM state_fuel_shares WHERE zone=%s AND as_of=%s", (zone, as_of))
        match_rate = (sum(own.values()) + covered * central_known) / total
        for fuel, v in blended.items():
            if v / total < 0.0005:
                continue
            conn.execute(
                """INSERT INTO state_fuel_shares (zone, as_of, fuel, share, match_rate, basis)
                   VALUES (%s,%s,%s,%s,%s,'psp_actual_t1')""",
                (zone, as_of, fuel, v / total, match_rate),
            )
        n += 1
    return n


def ingest(n_reports: int = 1, conn: psycopg.Connection | None = None,
           cfg: RegionCfg = NRLDC) -> int:
    own = conn is None
    if own:
        conn = psycopg.connect(get_dsn())
    registry = conn.execute("SELECT id, name, fuel FROM india_plants").fetchall()
    ok = 0
    with make_client(legacy_tls=True) as client:
        client.headers["X-Requested-With"] = "XMLHttpRequest"
        for doc in report_urls(client, cfg, n_reports):
            raw = request_raw(client, cfg.source, "GET", doc["url"],
                              meta={"kind": "report_pdf", "title": doc["title"]})
            as_of, err = ingest_pdf(conn, raw, registry, cfg)
            if err:
                print(f"  [{cfg.region}] QUARANTINED {doc['title']}: {err}", file=sys.stderr)
            else:
                ok += 1
                compute_psp_shares(conn, as_of, cfg)
            conn.commit()
            time.sleep(1.0)
    if own:
        conn.close()
    return ok


def latest_ingested(conn: psycopg.Connection, cfg: RegionCfg) -> date | None:
    return conn.execute(
        "SELECT max(as_of) FROM daily_state_energy WHERE source=%s", (cfg.source,)
    ).fetchone()[0]


def ensure_current(conn: psycopg.Connection) -> None:
    """Tick hook: ingest any region whose T-1 report isn't in yet."""
    yesterday = (datetime.now(IST) - timedelta(days=1)).date()
    for cfg in REGIONS.values():
        latest = latest_ingested(conn, cfg)
        if latest is None or latest < yesterday:
            print(f"[psp {cfg.region}] latest={latest}, fetching", file=sys.stderr)
            ingest(n_reports=1, conn=conn, cfg=cfg)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", choices=["ingest", "shares"])
    ap.add_argument("--region", default="NR", choices=sorted(REGIONS))
    ap.add_argument("--backfill", type=int, default=1, help="number of recent reports")
    ap.add_argument("--date", help="as_of for shares (YYYY-MM-DD)")
    args = ap.parse_args()
    cfg = REGIONS[args.region]
    if args.command == "ingest":
        ok = ingest(n_reports=args.backfill, cfg=cfg)
        print(f"[{cfg.region}] ingested {ok} reports", file=sys.stderr)
        return 0 if ok else 1
    with psycopg.connect(get_dsn()) as conn:
        as_of = date.fromisoformat(args.date) if args.date else latest_ingested(conn, cfg)
        n = compute_psp_shares(conn, as_of, cfg)
        conn.commit()
        print(f"[{cfg.region}] psp shares for {n} states ({as_of})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
