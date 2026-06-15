from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from gridscrapers.schema import Metric, RawResponse
from gridscrapers.sources import chhattisgarh_sldc

IST = ZoneInfo("Asia/Kolkata")
SAMPLE = Path(__file__).parents[2] / "docs/sources/sldccg_gen_sample.html"


def _raw(body: bytes) -> RawResponse:
    return RawResponse(
        source="chhattisgarh_sldc",
        endpoint=chhattisgarh_sldc.URL,
        fetched_at=datetime(2026, 6, 15, 16, 5, 0, tzinfo=IST),
        http_status=200,
        body=body,
        meta={"zone": "IN-CG"},
    )


def test_parse_generation_sample():
    points = chhattisgarh_sldc.parse(_raw(SAMPLE.read_bytes()))
    gen = {p.fuel: p.value for p in points if p.metric == Metric.GENERATION}
    # coal = TOTAL OF CSPGCL (2075) - Bango hydro (0) + Other Intrastate (387)
    assert abs(gen["coal"] - 2462.0) < 0.1
    assert abs(gen["solar"] - 279.0) < 0.1     # "Solar & Bess ... at 132 Level | 279"
    assert abs(gen["biomass"] - 43.0) < 0.1
    assert "hydro" not in gen                   # Bango at 0 MW is dropped


def test_parse_demand_frequency_and_timestamp():
    points = chhattisgarh_sldc.parse(_raw(SAMPLE.read_bytes()))
    by_metric = {p.metric: p for p in points}
    assert abs(by_metric[Metric.DEMAND_MET].value - 5480.0) < 0.1
    assert abs(by_metric[Metric.FREQUENCY].value - 49.99) < 0.01
    # "Updates Latest by 15-Jun-2026 16:02" IST, stored as UTC (10:32)
    assert by_metric[Metric.GENERATION].ts.isoformat() == "2026-06-15T10:32:00+00:00"


def test_all_measured_not_estimated():
    points = chhattisgarh_sldc.parse(_raw(SAMPLE.read_bytes()))
    assert points and all(p.estimated is False for p in points)
    assert all(p.zone == "IN-CG" for p in points)


def test_internal_reconcile_rejects_inconsistent_totals():
    # break the page's own arithmetic: CSPGCL + IPP/CPP no longer matches combined
    html = SAMPLE.read_text(encoding="utf-8", errors="replace")
    html = html.replace("2462", "9999")  # combined total now inconsistent
    assert chhattisgarh_sldc.parse(_raw(html.encode())) == []


def test_non_200_returns_empty():
    raw = RawResponse(
        source="chhattisgarh_sldc", endpoint=chhattisgarh_sldc.URL,
        fetched_at=datetime(2026, 6, 15, 16, 5, 0, tzinfo=IST),
        http_status=500, body=b"<html>error</html>", meta={"zone": "IN-CG"},
    )
    assert chhattisgarh_sldc.parse(raw) == []
