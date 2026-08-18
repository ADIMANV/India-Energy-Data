"""MERIT (meritindia.in) — live state demand / own generation (ISGS) / import.

POST /StateWiseDetails/BindCurrentStateStatus {"StateCode": "MHA"} →
[{"Demand":"27,044","ISGS":"16,813","ImportData":"10,231"}]  (MW, live)

State codes are MERIT's own codes, not ISO — see STATE_CODES below.
"""

import json
import time

from ..http import make_client, request_raw
from ..schema import Datapoint, Metric, RawResponse, Unit

SOURCE = "merit"
PARSER_VERSION = 1
BASE = "https://meritindia.in"
REQUEST_GAP_S = 0.5

# MERIT StateCode -> our zone id. Scraped 2026-06-11 from the hidden #StateCode
# input on every meritindia.in/state-data/<slug> page. Jammu & Kashmir has a
# page but no StateCode (MERIT doesn't cover it).
STATE_CODES: dict[str, str] = {
    "AP": "IN-AP",  # andhra-pradesh
    "ACP": "IN-AR",  # arunachal-pradesh
    "ASM": "IN-AS",  # assam
    "BHR": "IN-BR",  # bihar
    "CHG": "IN-CH",  # chandigarh
    "CTG": "IN-CG",  # chhattisgarh
    "DL": "IN-DL",  # delhi
    "GOA": "IN-GA",  # goa
    "GJT": "IN-GJ",  # gujarat
    "HRN": "IN-HR",  # haryana
    "HP": "IN-HP",  # himachal-pradesh
    "JHK": "IN-JH",  # jharkhand
    "KRT": "IN-KA",  # karnataka
    "KRL": "IN-KL",  # kerala
    "MPD": "IN-MP",  # madhya-pradesh
    "MHA": "IN-MH",  # maharashtra
    "MIP": "IN-MN",  # manipur
    "MGA": "IN-ML",  # meghalaya
    "MZM": "IN-MZ",  # mizoram
    "NGD": "IN-NL",  # nagaland
    "ODI": "IN-OD",  # odisha
    "PU": "IN-PY",  # puducherry
    "PNB": "IN-PB",  # punjab
    "RJ": "IN-RJ",  # rajasthan
    "SKM": "IN-SK",  # sikkim
    "TND": "IN-TN",  # tamil-nadu
    "TLG": "IN-TS",  # telangana
    "TPA": "IN-TR",  # tripura
    "UP": "IN-UP",  # uttar-pradesh
    "UTK": "IN-UK",  # uttarakhand
    "BGL": "IN-WB",  # west-bengal
}


def fetch() -> list[RawResponse]:
    raws: list[RawResponse] = []
    # verify=False: meritindia.in serves an incomplete cert chain (missing intermediate)
    with make_client(verify=False) as client:
        url = f"{BASE}/StateWiseDetails/BindCurrentStateStatus"
        for code, zone in STATE_CODES.items():
            raws.append(request_raw(
                client, SOURCE, "POST", url,
                json={"StateCode": code},
                meta={"zone": zone, "state_code": code},
            ))
            time.sleep(REQUEST_GAP_S)
    return raws


def _num(s: str | None) -> float | None:
    # fields are null for states with no own generation (e.g. Goa's ISGS)
    if s is None:
        return None
    s = s.replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def parse(raw: RawResponse) -> list[Datapoint]:
    if not raw.body or (raw.http_status or 0) != 200:
        return []
    data = json.loads(raw.body)
    if not isinstance(data, list) or not data:
        return []
    row = data[0]
    zone = raw.meta["zone"]
    # MERIT has no block timestamp on this endpoint; use fetch time rounded
    # down to the minute. The page itself polls this continuously.
    ts = raw.fetched_at.replace(second=0, microsecond=0)
    common = dict(zone=zone, ts=ts, unit=Unit.MW, source=SOURCE, parser_version=PARSER_VERSION)
    points = []
    if (v := _num(row.get("Demand", ""))) is not None:
        points.append(Datapoint(metric=Metric.DEMAND_MET, value=v, **common))
    if (v := _num(row.get("ISGS", ""))) is not None:
        points.append(Datapoint(metric=Metric.GENERATION, fuel="own_generation", value=v, **common))
    if (v := _num(row.get("ImportData", ""))) is not None:
        points.append(Datapoint(metric=Metric.NET_IMPORT, value=v, **common))
    return points
