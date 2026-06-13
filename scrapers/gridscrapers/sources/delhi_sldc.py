"""Delhi SLDC (delhisldc.org) — live in-state generation by fuel + demand.

The Redirect.aspx?Loc=0804 dashboard exposes a "DELHI GENERATION" table with
per-GENCO actual MW (timestamped). Delhi's own fleet is gas CCGTs + four
waste-to-energy plants; the bulk of supply is central imports (not its own
generation), so the measured mix here is Delhi's *in-state generation* mix —
see docs/sources/zone-provenance.md.

Fuel mapping is by GENCO (stable short codes):
  CCGT-Bawana / Pragati / GT  -> gas
  *SWSL / *WPL / TOWMP / TWEPL -> other  (municipal waste-to-energy)
"""

import re
from datetime import datetime

from bs4 import BeautifulSoup

from ..http import IST, make_client, request_raw
from ..schema import Datapoint, Metric, RawResponse, Unit

SOURCE = "delhi_sldc"
PARSER_VERSION = 1
ZONE = "IN-DL"
URL = "http://www.delhisldc.org/Redirect.aspx?Loc=0804"

GAS = {"CCGT-BAWANA", "PRAGATI", "GT"}
# everything else in the own-generation table is waste-to-energy
WASTE = {"DMSWSL-DSIDC", "EDWPL-GAZIPUR", "TOWMP-OKHLA", "TWEPL-TUGLAKABAD"}


def fetch() -> list[RawResponse]:
    with make_client(legacy_tls=True) as client:
        return [request_raw(client, SOURCE, "GET", URL, meta={"zone": ZONE})]


def _ts(soup: BeautifulSoup) -> datetime:
    m = re.search(r"DELHI GENERATION\s*\((\d{2}):(\d{2}):(\d{2})", soup.get_text(" "))
    now = datetime.now(IST)
    if m:
        return now.replace(hour=int(m.group(1)), minute=int(m.group(2)),
                           second=int(m.group(3)), microsecond=0)
    return now.replace(second=0, microsecond=0)


def parse(raw: RawResponse) -> list[Datapoint]:
    if not raw.body or (raw.http_status or 0) != 200:
        return []
    soup = BeautifulSoup(raw.body, "html.parser")
    ts = _ts(soup)

    # find the DELHI GENERATION table (header row: GENCO Schedule AS Actual UI)
    gen_table = None
    for tbl in soup.find_all("table"):
        cells = [c.get_text(strip=True) for c in tbl.find_all(["td", "th"])]
        if "GENCO" in cells and "Actual" in cells and "UI" in cells:
            gen_table = cells
            break
    if not gen_table:
        return []

    # the row sequence after the header is: name, schedule, as, actual, ui, ...
    by_fuel: dict[str, float] = {}
    i = gen_table.index("UI") + 1
    while i + 4 <= len(gen_table):
        name = gen_table[i].upper()
        if name in ("TOTAL", ""):
            break
        try:
            actual = float(gen_table[i + 3])
        except (ValueError, IndexError):
            break
        fuel = "gas" if name in GAS else "other"
        by_fuel[fuel] = by_fuel.get(fuel, 0.0) + max(actual, 0.0)
        i += 5

    return [
        Datapoint(zone=ZONE, ts=ts, metric=Metric.GENERATION, fuel=fuel,
                  value=round(mw, 1), unit=Unit.MW, source=SOURCE,
                  parser_version=PARSER_VERSION, estimated=False)
        for fuel, mw in by_fuel.items() if mw > 0
    ]
