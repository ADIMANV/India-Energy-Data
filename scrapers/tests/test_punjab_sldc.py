from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from gridscrapers.schema import Metric, RawResponse
from gridscrapers.sources import punjab_sldc

IST = ZoneInfo("Asia/Kolkata")
SAMPLES = Path(__file__).parents[2] / "docs/sources"


def _raw(body: bytes, endpoint: str) -> RawResponse:
    return RawResponse(
        source="punjab_sldc",
        endpoint=f"https://sldcapi.pstcl.org/wsDataService.asmx/{endpoint}",
        fetched_at=datetime(2026, 6, 11, 18, 0, 30, tzinfo=IST),
        http_status=200,
        body=body,
        meta={"zone": "IN-PB", "endpoint": endpoint},
    )


def test_parse_generation_sample():
    raw = _raw((SAMPLES / "pstcl_pbGenData2.json").read_bytes(), "pbGenData2")
    points = punjab_sldc.parse(raw)
    by_fuel = {p.fuel: p.value for p in points}
    assert set(by_fuel) == {"coal", "hydro", "solar", "biomass"}
    # totalThermal 1049.03516 + totalIpp 2114.51172
    assert abs(by_fuel["coal"] - 3163.5) < 0.1
    assert abs(by_fuel["hydro"] - 993.4) < 0.1
    # fuels sum ≈ grossGeneration (4274.5) within 0.5%
    assert abs(sum(by_fuel.values()) - 4274.5) / 4274.5 < 0.005
    # SCADA has no ts on this endpoint: fetch time, minute resolution
    assert points[0].ts.isoformat() == "2026-06-11T12:30:00+00:00"


def test_parse_dynamic_data_sample():
    raw = _raw((SAMPLES / "pstcl_dynamicData.json").read_bytes(), "dynamicData")
    points = punjab_sldc.parse(raw)
    by_metric = {p.metric: p for p in points}
    assert by_metric[Metric.DEMAND_MET].value == 11098.0
    assert by_metric[Metric.FREQUENCY].value == 50.05
    # updateDate 11-06-2026 17:59:44 IST == 12:29:44 UTC
    assert by_metric[Metric.DEMAND_MET].ts.isoformat() == "2026-06-11T12:29:44+00:00"
