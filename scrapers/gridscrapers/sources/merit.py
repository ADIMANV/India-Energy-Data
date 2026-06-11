"""MERIT (meritindia.in) — live state demand / own generation (ISGS) / import.

POST /StateWiseDetails/BindCurrentStateStatus {"StateCode": "MHA"} →
[{"Demand":"27,044","ISGS":"16,813","ImportData":"10,231"}]  (MW, live)

State codes are MERIT's own 3-letter codes, not ISO. Mapping below was taken
from the hidden #StateCode inputs on meritindia.in/state-data/<slug> pages and
the homepage hover map; codes not yet verified are commented out.
"""

import json
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from ..schema import Datapoint, Metric, RawResponse, Unit

SOURCE = "merit"
PARSER_VERSION = 1
BASE = "https://meritindia.in"
IST = ZoneInfo("Asia/Kolkata")
UA = "india-grid-map/0.1 (open data project; contact: adityamsawant07@gmail.com)"
REQUEST_GAP_S = 0.5

# MERIT StateCode -> our zone id (seen on homepage map: MHA, PNB, DL, AP, KRL,
# TND, ODI, BHR, CHG/CTG, MPD, ACP, MIP ... verify per state before enabling)
STATE_CODES: dict[str, str] = {
    "MHA": "IN-MH",
    "PNB": "IN-PB",
    "DL": "IN-DL",
    "AP": "IN-AP",
    "KRL": "IN-KL",
    "TND": "IN-TN",
    "ODI": "IN-OD",
    "BHR": "IN-BR",
}


def fetch() -> list[RawResponse]:
    raws: list[RawResponse] = []
    # verify=False: meritindia.in serves an incomplete cert chain (missing intermediate)
    with httpx.Client(verify=False, headers={"User-Agent": UA}, timeout=30) as client:
        for code, zone in STATE_CODES.items():
            url = f"{BASE}/StateWiseDetails/BindCurrentStateStatus"
            try:
                resp = client.post(url, json={"StateCode": code})
            except httpx.HTTPError as e:
                raws.append(RawResponse(
                    source=SOURCE, endpoint=url, fetched_at=datetime.now(IST),
                    http_status=None, body=b"", meta={"zone": zone, "state_code": code, "error": str(e)},
                ))
                continue
            raws.append(RawResponse(
                source=SOURCE,
                endpoint=url,
                fetched_at=datetime.now(IST),
                http_status=resp.status_code,
                content_type=resp.headers.get("content-type"),
                body=resp.content,
                meta={"zone": zone, "state_code": code},
            ))
            time.sleep(REQUEST_GAP_S)
    return raws


def _num(s: str) -> float | None:
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
