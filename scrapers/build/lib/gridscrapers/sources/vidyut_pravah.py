"""Vidyut Pravah (vidyutpravah.in) — state-wise demand met, exchange purchase/price,
yesterday's shortage; national demand from the homepage.

Quirks (see docs/sources/README.md): apex domain only, invalid TLS cert,
values update per 15-minute time block, IST.
"""

import re
import time
from datetime import datetime, timedelta

from bs4 import BeautifulSoup

from ..http import IST, make_client, request_raw
from ..schema import Datapoint, Metric, RawResponse, Unit
from ..zones import NATIONAL, VIDYUT_PRAVAH_SLUGS

SOURCE = "vidyut_pravah"
PARSER_VERSION = 1
BASE = "https://vidyutpravah.in"
REQUEST_GAP_S = 0.5

_NUM = re.compile(r"[-+]?[\d,]*\.?\d+")


def _num(text: str) -> float | None:
    m = _NUM.search(text.replace(",", ""))
    return float(m.group()) if m else None


def fetch() -> list[RawResponse]:
    raws: list[RawResponse] = []
    # verify=False: vidyutpravah.in serves an invalid TLS cert (recon doc)
    with make_client(verify=False) as client:
        targets = [("/", {"zone": NATIONAL})] + [
            (f"/state-data/{slug}", {"zone": zone, "slug": slug})
            for slug, zone in VIDYUT_PRAVAH_SLUGS.items()
        ]
        for path, meta in targets:
            raws.append(request_raw(client, SOURCE, "GET", BASE + path, meta=meta))
            time.sleep(REQUEST_GAP_S)
    return raws


def _block_start(soup: BeautifulSoup, fetched_at: datetime) -> datetime:
    """Timestamp of the 15-min block from 'TIME BLOCK 12:30 - 12:45 DATED 11 JUN 2026'."""
    text = soup.get_text(" ")
    m = re.search(r"TIME BLOCK\s+(\d{1,2}:\d{2})\s*-\s*\d{1,2}:\d{2}\s+DATED\s+(\d{1,2} [A-Z]{3} \d{4})", text)
    if not m:
        raise ValueError("time block header not found")
    dt = datetime.strptime(f"{m.group(2)} {m.group(1)}", "%d %b %Y %H:%M")
    return dt.replace(tzinfo=IST)


def _span_value(soup: BeautifulSoup, cls: str) -> float | None:
    el = soup.find("span", class_=cls)
    return _num(el.get_text()) if el else None


def parse(raw: RawResponse) -> list[Datapoint]:
    if not raw.body or (raw.http_status or 0) != 200:
        return []
    zone = raw.meta["zone"]
    soup = BeautifulSoup(raw.body, "html.parser")
    ts = _block_start(soup, raw.fetched_at)
    common = dict(source=SOURCE, parser_version=PARSER_VERSION)
    points: list[Datapoint] = []

    def add(metric: Metric, value: float | None, unit: Unit, *, z: str = zone, t: datetime = ts) -> None:
        if value is not None:
            points.append(Datapoint(zone=z, ts=t, metric=metric, value=value, unit=unit, **common))

    if zone == NATIONAL:
        cur = soup.find("span", id="CurrentDemandMET")
        prev = soup.find("span", id="PrevDemandMET")
        # homepage reports national demand in GW; store MW
        if cur and (v := _num(cur.get_text())) is not None:
            add(Metric.DEMAND_MET, v * 1000, Unit.MW)
        if prev and (v := _num(prev.get_text())) is not None:
            add(Metric.DEMAND_MET, v * 1000, Unit.MW, t=ts - timedelta(days=1))
        return points

    add(Metric.DEMAND_MET, _span_value(soup, "value_DemandMET_en"), Unit.MW)
    add(Metric.EXCHANGE_PURCHASE, _span_value(soup, "value_PowerPurchase_en"), Unit.MW)
    add(Metric.EXCHANGE_PRICE, _span_value(soup, "value_ExchangePrice_en"), Unit.INR_PER_KWH)
    yday = ts - timedelta(days=1)
    add(Metric.DEMAND_MET, _span_value(soup, "value_PrevDemandMET_en"), Unit.MW, t=yday)
    add(Metric.EXCHANGE_PURCHASE, _span_value(soup, "value_PrevPowerPurchase_en"), Unit.MW, t=yday)
    add(Metric.EXCHANGE_PRICE, _span_value(soup, "value_PrevExchangePrice_en"), Unit.INR_PER_KWH, t=yday)

    # "Shortage For Yesterday" — attach to yesterday's date (midnight IST)
    yday_midnight = ts.replace(hour=0, minute=0) - timedelta(days=1)
    add(Metric.PEAK_SHORTAGE, _span_value(soup, "value_PeakDemand_en"), Unit.MW, t=yday_midnight)
    add(Metric.ENERGY_SHORTAGE, _span_value(soup, "value_TotalEnergy_en"), Unit.MU, t=yday_midnight)
    return points
