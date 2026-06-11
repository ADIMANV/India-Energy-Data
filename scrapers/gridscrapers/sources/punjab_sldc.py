"""Punjab SLDC (sldcapi.pstcl.org) — live SCADA generation by fuel for IN-PB.

Two JSON GET endpoints (no auth):
  pbGenData2  — per-plant + aggregate generation MW. Fuel mapping follows
                electricitymaps IN_PB: totalThermal (state coal) + totalIpp
                (private coal: GVK/Rajpura/Talwandi Sabo) → coal;
                totalHydro → hydro; resSolar → solar; resNonSolar → biomass.
                Aggregates reconcile with grossGeneration to ~0.25%.
  dynamicData — updateDate (authoritative SCADA time), frequencyHz, loadMW
                (state demand), drawalMW (import from grid), scheduleMW.

SCADA quality flags ("OK"/"SUSPECT") ride along in raw archive; values
reconcile regardless, so parsing does not filter on them.
"""

import time
from datetime import datetime

from ..http import IST, make_client, request_raw
from ..schema import Datapoint, Metric, RawResponse, Unit

SOURCE = "punjab_sldc"
PARSER_VERSION = 1
BASE = "https://sldcapi.pstcl.org/wsDataService.asmx"
ZONE = "IN-PB"
REQUEST_GAP_S = 0.5

FUEL_KEYS = {
    "totalThermal": "coal",
    "totalIpp": "coal",
    "totalHydro": "hydro",
    "resSolar": "solar",
    "resNonSolar": "biomass",
}


def fetch() -> list[RawResponse]:
    raws = []
    with make_client() as client:
        for endpoint in ["pbGenData2", "dynamicData"]:
            raws.append(request_raw(
                client, SOURCE, "GET", f"{BASE}/{endpoint}",
                meta={"zone": ZONE, "endpoint": endpoint},
            ))
            time.sleep(REQUEST_GAP_S)
    return raws


def _value(node) -> float | None:
    if isinstance(node, dict):
        node = node.get("value")
    return float(node) if isinstance(node, (int, float)) else None


def parse(raw: RawResponse) -> list[Datapoint]:
    import json

    if not raw.body or (raw.http_status or 0) != 200:
        return []
    data = json.loads(raw.body)
    endpoint = raw.meta["endpoint"]
    common = dict(zone=ZONE, source=SOURCE, parser_version=PARSER_VERSION)
    points: list[Datapoint] = []

    if endpoint == "dynamicData":
        ts = datetime.strptime(data["updateDate"], "%d-%m-%Y %H:%M:%S").replace(tzinfo=IST)
        if (v := _value(data.get("loadMW"))) is not None:
            points.append(Datapoint(ts=ts, metric=Metric.DEMAND_MET, value=v, unit=Unit.MW, **common))
        if (v := _value(data.get("drawalMW"))) is not None:
            points.append(Datapoint(ts=ts, metric=Metric.NET_IMPORT, value=v, unit=Unit.MW, **common))
        if (v := _value(data.get("frequencyHz"))) is not None:
            points.append(Datapoint(ts=ts, metric=Metric.FREQUENCY, value=v, unit=Unit.HZ, **common))
        return points

    # pbGenData2 carries no timestamp; SCADA refreshes continuously, so use
    # fetch time rounded to the minute (dynamicData.updateDate tracks it ±1 min)
    ts = raw.fetched_at.replace(second=0, microsecond=0)
    by_fuel: dict[str, float] = {}
    for key, fuel in FUEL_KEYS.items():
        v = _value(data.get(key))
        if v is not None:
            by_fuel[fuel] = by_fuel.get(fuel, 0.0) + max(v, 0.0)
    for fuel, mw in by_fuel.items():
        points.append(Datapoint(
            ts=ts, metric=Metric.GENERATION, fuel=fuel, value=mw, unit=Unit.MW, **common
        ))
    return points
