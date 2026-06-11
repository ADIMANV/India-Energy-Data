from datetime import datetime
from zoneinfo import ZoneInfo

from gridscrapers.schema import Metric, RawResponse
from gridscrapers.sources import merit

IST = ZoneInfo("Asia/Kolkata")


def _raw(body: bytes) -> RawResponse:
    return RawResponse(
        source="merit",
        endpoint="https://meritindia.in/StateWiseDetails/BindCurrentStateStatus",
        fetched_at=datetime(2026, 6, 11, 13, 0, tzinfo=IST),
        http_status=200,
        body=body,
        meta={"zone": "IN-GA", "state_code": "GOA"},
    )


def test_parse_full_row():
    pts = merit.parse(_raw(b'[{"Demand":"27,044","ISGS":"16,813","ImportData":"10,231"}]'))
    by_metric = {p.metric: p.value for p in pts}
    assert by_metric == {
        Metric.DEMAND_MET: 27044.0,
        Metric.GENERATION: 16813.0,
        Metric.NET_IMPORT: 10231.0,
    }


def test_parse_null_isgs():
    """States with no own generation (Goa, Chandigarh, ...) return ISGS: null."""
    pts = merit.parse(_raw(b'[{"Demand":"635","ISGS":null,"ImportData":"635"}]'))
    assert {p.metric for p in pts} == {Metric.DEMAND_MET, Metric.NET_IMPORT}


def test_parse_failed_fetch_returns_empty():
    raw = _raw(b"")
    raw.http_status = None
    assert merit.parse(raw) == []
