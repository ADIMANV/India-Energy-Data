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


# --- state headers ------------------------------------------------------------

def test_every_state_header_is_recognised_or_deliberately_skipped():
    # dgr2 spells Chhattisgarh "CHHATISGARH"; until that was mapped, its
    # stations ran on under the state printed before it (Uttar Pradesh)
    import xlrd

    from gridscrapers.cea import IGNORED_HEADERS, STATE_NAMES

    sh = xlrd.open_workbook(file_contents=SAMPLE.read_bytes()).sheet_by_index(0)
    col = [str(sh.cell_value(r, 0)).strip().upper() for r in range(sh.nrows)]
    headers = {col[r] for r in range(len(col) - 1) if col[r + 1] == "STATE TOTAL"}
    assert headers - set(STATE_NAMES) - IGNORED_HEADERS == set()


def test_chhattisgarh_generation_is_its_own(parsed):
    rows, _ = parsed
    cg = sum(r["actual_mu"] or 0 for r in rows if r["zone"] == "IN-CG")
    up = sum(r["actual_mu"] or 0 for r in rows if r["zone"] == "IN-UP")
    assert 400 < cg < 520 and 500 < up < 620       # 455 and 562 MU on 10 June


def test_unknown_header_ends_the_previous_state():
    from gridscrapers.cea import header_zone

    assert header_zone("CHHATISGARH", "STATE TOTAL") == (True, "IN-CG")
    assert header_zone("BHUTAN", "STATE TOTAL") == (True, None)
    assert header_zone("SIPAT STPS", "UNIT") == (False, None)


# --- station and unit status --------------------------------------------------

@pytest.fixture(scope="module")
def stations():
    from gridscrapers.cea import parse_station_status

    return {s["station_key"]: s for s in parse_station_status(SAMPLE.read_bytes(), date(2026, 6, 10))}


def test_stations_land_in_their_own_state(stations):
    assert "IN-CG|sipat stps" in stations and "IN-UP|sipat stps" not in stations
    sipat = stations["IN-CG|sipat stps"]
    assert (sipat["sector"], sipat["fuel"], sipat["monitored_mw"]) == ("CENTRAL", "coal", 2980.0)


def test_units_carry_outage_size_start_and_reason(stations):
    y = stations["IN-TS|yadadri tps"]
    assert (y["monitored_mw"], y["outage_mw"]) == (3200.0, 2400.0)
    down = {u["unit"]: u for u in y["units"] if u["out_mw"]}
    assert down["2"]["out_mw"] == 800.0
    assert down["2"]["since"] == "2026-06-08T10:41"
    assert down["2"]["remark"] == "BOILER AUX. MISC. PROMLEMS" and down["2"]["kind"] == "forced"
    assert y["units"][0]["unit"] == "1" and y["units"][0]["since"] is None


def test_national_station_totals(stations):
    assert 500 < len(stations) < 560
    assert 300_000 < sum(s["monitored_mw"] for s in stations.values()) < 320_000


def test_outage_reasons_fall_into_kinds():
    from gridscrapers.cea import outage_kind

    assert outage_kind("RESERVE SHUT DOWN") == "reserve"
    assert outage_kind("Low schedule") == "reserve"
    assert outage_kind("COAL SHORTAGE") == "fuel"
    assert outage_kind("ANNUAL OVERHAUL") == "planned"
    assert outage_kind("BOILER TUBE LEAKAGE") == "forced"
    assert outage_kind("") == "unstated"


def test_station_key_folds_case_and_punctuation():
    from gridscrapers.cea import station_key

    assert station_key("IN-CG", "KORBA-WEST  TPS") == "IN-CG|korba west tps"
    assert station_key("IN-AP", "Dr. N.TATA RAO TPS") == "IN-AP|dr n tata rao tps"


def test_missing_days_finds_holes_not_just_yesterday():
    from datetime import date as d

    from gridscrapers.cea import missing_days

    class Conn:
        def execute(self, sql, params):
            class R:
                def fetchall(_):
                    return [(d(2026, 11, 19),), (d(2026, 11, 17),), (d(2026, 11, 16),),
                            (d(2026, 11, 15),), (d(2026, 11, 14),)]
            return R()

    # 20 Nov was published late and missed; 21 Nov isn't out yet; 18 Nov is a hole
    assert missing_days(Conn(), d(2026, 11, 21)) == [d(2026, 11, 18), d(2026, 11, 20), d(2026, 11, 21)]
