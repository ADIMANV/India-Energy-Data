from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from gridscrapers import capacity
from gridscrapers.schema import RawResponse

IST = ZoneInfo("Asia/Kolkata")
SAMPLE = Path(__file__).parents[2] / "docs/sources/CEA_IC_July2026.xlsx"


def _raw(body: bytes) -> RawResponse:
    return RawResponse(
        source="cea_capacity",
        endpoint=capacity.report_url(date(2026, 7, 1)),
        fetched_at=datetime(2026, 8, 24, 12, 0, tzinfo=IST),
        http_status=200,
        body=body,
        meta={"month": "2026-07-01"},
    )


def test_report_url_month_name():
    # CEA's filename uses the full month name with no separator before the year
    assert capacity.report_url(date(2026, 7, 1)).endswith("/2026/07/IC_July2026.xlsx")


def test_parses_state_sector_fuel():
    rows = capacity.parse(_raw(SAMPLE.read_bytes()))
    assert rows, "no rows parsed"
    # as_of comes from the workbook's own "(As on 31.07.2026)" caption
    assert {r[0] for r in rows} == {date(2026, 7, 31)}
    assert {r[2] for r in rows} == {"state", "private", "central"}
    assert {r[3] for r in rows} <= {"coal", "lignite", "gas", "diesel",
                                    "nuclear", "hydro", "res"}


def test_covers_the_major_states():
    zones = {r[1] for r in capacity.parse(_raw(SAMPLE.read_bytes()))}
    for z in ("IN-MH", "IN-GJ", "IN-TN", "IN-RJ", "IN-UP", "IN-KA", "IN-WB"):
        assert z in zones, f"{z} missing"
    # regional subtotals and the NLC/DVC central undertakings are not zones
    assert all(z.startswith("IN-") for z in zones)


def test_delhi_matches_the_published_workbook():
    rows = capacity.parse(_raw(SAMPLE.read_bytes()))
    dl = {(s, f): mw for _, z, s, f, mw in rows if z == "IN-DL"}
    # row 75: Delhi / State / gas 1800.4
    assert abs(dl[("state", "gas")] - 1800.4) < 0.1
    # row 76: Delhi / Private / coal 878.22
    assert abs(dl[("private", "coal")] - 878.22) < 0.01


def test_national_total_is_in_the_right_ballpark():
    rows = capacity.parse(_raw(SAMPLE.read_bytes()))
    total_gw = sum(r[4] for r in rows) / 1000
    # CEA reported ~533 GW all-India around this period; state rows exclude the
    # NLC/DVC undertakings, so this is close but deliberately not identical.
    assert 480 < total_gw < 580, total_gw


def test_bad_fetch_returns_empty():
    assert capacity.parse(_raw(b"")) == []
    not_xlsx = _raw(b"<html>error</html>")
    assert capacity.parse(not_xlsx) == []
