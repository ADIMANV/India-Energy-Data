"""Chhattisgarh SLDC (sldccg.com) — live in-state generation by fuel.

The /gen.php "CG System Overview" is a plain HTML page (refresh 30s) with two
tables: CSPGCL GENERATION (station unit rows + per-station TOTALs, then
"TOTAL OF CSPGCL", "Other Intrastate Injection" = intra-state IPP/CPP, and
"TOTAL OF CSPGCL & IPP/CPP") and CG SYSTEM SUMMARY ("CG Demand", "WR Frequency",
"Solar & Bess Injection ...", "Biomass Injection", "CG Drawl from Central
Sector").

Fuel mapping: CSPGCL thermal (Korba West / DSPM / Marwa) + intra-state IPP/CPP
are coal (CG's IPP/CPP fleet is coal-dominated); Bango HPS is hydro; the two
injection lines are solar and biomass. coal is derived as
`TOTAL_OF_CSPGCL − bango_hydro + other_intrastate`, so a new thermal unit is
captured automatically without per-station mapping.

Internal reconcile gate: the page's own "TOTAL OF CSPGCL & IPP/CPP" must equal
"TOTAL OF CSPGCL" + "Other Intrastate Injection" within tolerance, else the read
is rejected (return []) rather than emitting a mismatched mix.

CG is a measured *in-state generation* mix: ~half its demand is central-sector
drawl (generated elsewhere, a mixed pool), so the mix is partial-by-design and
exempt from the demand reconcile guard (see sources.OWN_GENERATION_SOURCES).
Counting only in-state generation is correct for the generation-weighted
national CI (central drawl is counted in the states that generate it). The
state-level CG CI is therefore in-state-generation CI (coal-heavy), not
consumption CI.
"""

import re
from datetime import datetime

from bs4 import BeautifulSoup

from ..http import IST, make_client, request_raw
from ..schema import Datapoint, Metric, RawResponse, Unit

SOURCE = "chhattisgarh_sldc"
PARSER_VERSION = 1
ZONE = "IN-CG"
URL = "https://sldccg.com/gen.php"
RECONCILE_TOL = 0.05  # CSPGCL + IPP/CPP must equal the stated combined total


def fetch() -> list[RawResponse]:
    with make_client(legacy_tls=True) as client:
        return [request_raw(client, SOURCE, "GET", URL, meta={"zone": ZONE})]


def _num(s: str) -> float | None:
    try:
        return float(s.replace(",", "").strip())
    except (ValueError, AttributeError):
        return None


def _ts(text: str, fallback: datetime) -> datetime:
    m = re.search(r"Updates?\s+Latest\s+by\s+(\d{1,2}-[A-Za-z]{3}-\d{4}\s+\d{1,2}:\d{2})",
                  text, re.I)
    if m:
        try:
            return datetime.strptime(m.group(1), "%d-%b-%Y %H:%M").replace(tzinfo=IST)
        except ValueError:
            pass
    return fallback.replace(second=0, microsecond=0)


def parse(raw: RawResponse) -> list[Datapoint]:
    if not raw.body or (raw.http_status or 0) != 200:
        return []
    soup = BeautifulSoup(raw.body, "html.parser")

    section: str | None = None
    section_total: dict[str, float] = {}   # station section -> its TOTAL row
    summary: dict[str, float] = {}         # every other "label | number" row
    for tr in soup.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        cells = [c for c in cells if c]
        if len(cells) == 1:
            up = cells[0].upper()
            if any(k in up for k in ("KORBA", "DSPM", "BANGO", "MARWA", "HPS", "TPS")):
                section = up
        elif len(cells) == 2:
            val = _num(cells[1])
            if val is None:
                continue
            if cells[0].strip().upper() == "TOTAL":
                if section:
                    section_total[section] = val
            else:
                summary[cells[0].strip().upper()] = val

    def look(*keys: str, contains: bool = False) -> float | None:
        for k in (k.upper() for k in keys):
            if contains:
                for lab, v in summary.items():
                    if k in lab:
                        return v
            elif k in summary:
                return summary[k]
        return None

    cspgcl = look("TOTAL OF CSPGCL")
    if cspgcl is None:
        return []
    combined = look("TOTAL OF CSPGCL & IPP/CPP")
    other_intra = look("OTHER INTRASTATE INJECTION") or 0.0
    # internal reconcile: the page's own subtotals must be self-consistent
    if combined is not None and abs((cspgcl + other_intra) - combined) > RECONCILE_TOL * max(combined, 1.0):
        return []

    bango = next((v for k, v in section_total.items() if "BANGO" in k), 0.0)
    hydro = max(bango, 0.0)
    by_fuel = {
        "coal": max(cspgcl - hydro, 0.0) + max(other_intra, 0.0),
        "hydro": hydro,
        "solar": max(look("SOLAR & BESS", "SOLAR", contains=True) or 0.0, 0.0),
        "biomass": max(look("BIOMASS", contains=True) or 0.0, 0.0),
    }
    demand = look("CG DEMAND")
    freq = look("WR FREQUENCY", "FREQUENCY", contains=True)

    ts = _ts(soup.get_text(" "), raw.fetched_at)
    common = dict(zone=ZONE, ts=ts, source=SOURCE, parser_version=PARSER_VERSION,
                  estimated=False)
    pts = [Datapoint(metric=Metric.GENERATION, fuel=f, value=round(v, 1), unit=Unit.MW, **common)
           for f, v in by_fuel.items() if v > 0]
    if demand and demand > 0:
        pts.append(Datapoint(metric=Metric.DEMAND_MET, value=round(demand, 1), unit=Unit.MW, **common))
    if freq and 45 < freq < 55:
        pts.append(Datapoint(metric=Metric.FREQUENCY, value=round(freq, 2), unit=Unit.HZ, **common))
    return pts
