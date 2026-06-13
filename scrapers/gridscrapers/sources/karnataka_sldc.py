"""Karnataka SLDC (kptclsldc.in) — full live in-state generation by fuel.

Two pages:
  StateGen.aspx — station-wise total generation (coal TPS + state hydro).
  StateNCEP.aspx — non-conventional: the TOTAL_IPPS row gives biomass,
    cogen, mini-hydro, wind, solar MW, plus the Pavagada solar park line.

Karnataka generates most of its own supply, so the measured mix is broadly
representative of consumption. Timestamp from the page (DD/MM/YYYY HH:MM:SS).
"""

import re
from datetime import datetime

from bs4 import BeautifulSoup

from ..http import IST, make_client, request_raw
from ..schema import Datapoint, Metric, RawResponse, Unit

SOURCE = "karnataka_sldc"
PARSER_VERSION = 1
ZONE = "IN-KA"
GEN_URL = "https://kptclsldc.in/StateGen.aspx"
NCEP_URL = "https://kptclsldc.in/StateNCEP.aspx"

# StateGen stations -> fuel (everything not listed is state hydro)
COAL_STATIONS = {"RTPS", "BTPS", "YTPS", "JINDAL", "UPCL"}
GAS_STATIONS = {"YCCP"}
# NCEP TOTAL_IPPS column order: bio-mass, cogen, mini-hydro, wind, solar.
# Mini-hydro is dropped (None): it would collide with the StateGen 'hydro'
# key on a different page timestamp and is <1% of generation.
NCEP_FUELS = ["biomass", "biomass", None, "wind", "solar"]


def fetch() -> list[RawResponse]:
    raws = []
    with make_client(legacy_tls=True) as client:
        raws.append(request_raw(client, SOURCE, "GET", GEN_URL, meta={"zone": ZONE, "page": "gen"}))
        raws.append(request_raw(client, SOURCE, "GET", NCEP_URL, meta={"zone": ZONE, "page": "ncep"}))
    return raws


def _ts(text: str) -> datetime:
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})\s+(\d{2}):(\d{2}):(\d{2})", text)
    if m:
        d, mo, y, h, mi, s = map(int, m.groups())
        return datetime(y, mo, d, h, mi, s, tzinfo=IST)
    return datetime.now(IST).replace(second=0, microsecond=0)


def _num(s: str) -> float | None:
    try:
        return float(s.replace(",", ""))
    except (ValueError, AttributeError):
        return None


def _parse_gen(raw: RawResponse) -> tuple[dict[str, float], datetime | None]:
    soup = BeautifulSoup(raw.body, "html.parser")
    by_fuel: dict[str, float] = {}
    for tbl in soup.find_all("table"):
        if "RTPS" not in tbl.get_text():
            continue
        for tr in tbl.find_all("tr"):
            cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            if len(cells) < 3:
                continue
            name = cells[0].upper()
            gen = _num(cells[2])  # CAP, TOTAL GENERATION, UNIT 1...
            if gen is None or name in ("GENERATING STATIONS", "TOTAL"):
                continue
            fuel = "coal" if name in COAL_STATIONS else "gas" if name in GAS_STATIONS else "hydro"
            by_fuel[fuel] = by_fuel.get(fuel, 0.0) + max(gen, 0.0)
        break
    return by_fuel, _ts(soup.get_text(" "))


def _parse_ncep(raw: RawResponse) -> dict[str, float]:
    soup = BeautifulSoup(raw.body, "html.parser")
    by_fuel: dict[str, float] = {}
    text_cells = None
    for tbl in soup.find_all("table"):
        if "TOTAL_IPPS" in tbl.get_text():
            for tr in tbl.find_all("tr"):
                cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                if cells and cells[0].upper().replace(" ", "") == "TOTAL_IPPS":
                    text_cells = cells
                    break
            break
    if text_cells:
        nums = [_num(c) for c in text_cells[1:]]
        for fuel, val in zip(NCEP_FUELS, nums):
            if fuel and val:
                by_fuel[fuel] = by_fuel.get(fuel, 0.0) + val
    # Pavagada solar park (state share) appears as its own line
    m = re.search(r"PAVAGADA SOLAR PARK\s*(\d+)", soup.get_text(" "), re.I)
    if m:
        by_fuel["solar"] = by_fuel.get("solar", 0.0) + float(m.group(1))
    return by_fuel


def parse(raw: RawResponse) -> list[Datapoint]:
    if not raw.body or (raw.http_status or 0) != 200:
        return []
    page = raw.meta.get("page")
    if page == "gen":
        by_fuel, ts = _parse_gen(raw)
    elif page == "ncep":
        by_fuel, ts = _parse_ncep(raw), datetime.now(IST).replace(second=0, microsecond=0)
    else:
        return []
    return [
        Datapoint(zone=ZONE, ts=ts, metric=Metric.GENERATION, fuel=fuel,
                  value=round(mw, 1), unit=Unit.MW, source=SOURCE,
                  parser_version=PARSER_VERSION, estimated=False)
        for fuel, mw in by_fuel.items() if mw > 0
    ]
