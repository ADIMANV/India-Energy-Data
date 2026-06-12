"""CEA dgr2 parser regression against the archived 2026-06-10 sample."""

from datetime import date
from pathlib import Path

import pytest

from gridscrapers.cea import parse_dgr2

SAMPLE = Path(__file__).parents[2] / "docs/sources/NPP_dgr2_100626.xls"


@pytest.fixture(scope="module")
def parsed():
    return parse_dgr2(SAMPLE.read_bytes(), date(2026, 6, 10))


def test_validates_clean(parsed):
    rows, errors = parsed
    assert errors == []
    assert len(rows) > 100


def test_haryana_sectors(parsed):
    rows, _ = parsed
    hr = {(r["sector"], r["fuel"]): r for r in rows if r["zone"] == "IN-HR"}
    # values straight from the sample: STATE/THERMAL actual 41.67 MU
    assert abs(hr[("STATE", "coal")]["actual_mu"] - 41.67) < 0.01
    assert abs(hr[("PVT", "coal")]["actual_mu"] - 22.55) < 0.01
    assert hr[("CENTRAL", "coal")]["capacity_mw"] == 1500.0


def test_national_coverage(parsed):
    rows, _ = parsed
    zones = {r["zone"] for r in rows}
    # all five regions represented, not just NR
    assert {"IN-MH", "IN-WB", "IN-AS", "IN-TN", "IN-PB"} <= zones


def test_fuel_normalization(parsed):
    rows, _ = parsed
    fuels = {r["fuel"] for r in rows}
    assert fuels <= {"coal", "gas", "oil", "hydro", "nuclear", "other"}
