"""Parser regression test against the archived sample from 2026-06-11 recon."""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from gridscrapers.schema import Metric, RawResponse
from gridscrapers.sources import vidyut_pravah

SAMPLE = Path(__file__).parents[2] / "docs/sources/vidyutpravah_state_maharashtra.html"
IST = ZoneInfo("Asia/Kolkata")


def _raw(body: bytes, zone: str) -> RawResponse:
    return RawResponse(
        source="vidyut_pravah",
        endpoint="https://vidyutpravah.in/state-data/maharashtra",
        fetched_at=datetime(2026, 6, 11, 12, 40, tzinfo=IST),
        http_status=200,
        body=body,
        meta={"zone": zone},
    )


def test_parse_state_page():
    points = vidyut_pravah.parse(_raw(SAMPLE.read_bytes(), "IN-MH"))
    by_key = {(p.metric, p.ts.isoformat()): p for p in points}

    cur = by_key[(Metric.DEMAND_MET, "2026-06-11T07:00:00+00:00")]  # 12:30 IST block
    assert cur.value == 27042.0
    prev = by_key[(Metric.DEMAND_MET, "2026-06-10T07:00:00+00:00")]
    assert prev.value == 24816.0
    price = by_key[(Metric.EXCHANGE_PRICE, "2026-06-11T07:00:00+00:00")]
    assert price.value == 1.31
    purchase = by_key[(Metric.EXCHANGE_PURCHASE, "2026-06-11T07:00:00+00:00")]
    assert purchase.value == 828.0
    assert all(p.zone == "IN-MH" for p in points)


def test_parse_failed_fetch_returns_empty():
    assert vidyut_pravah.parse(_raw(b"", "IN-MH")) == []
